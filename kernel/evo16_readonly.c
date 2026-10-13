// SPDX-License-Identifier: GPL-2.0-only
/*
 * Experimental EVO 16 UAC2 read transport. This is not a USB interface driver:
 * it never binds, claims, detaches or requests reset/configuration/firmware
 * operations. Ordinary USB runtime-PM recovery remains usbcore's responsibility.
 * Only explicitly allowed class/interface IN requests can reach endpoint zero.
 *
 * USB lifecycle/PM API references: Linux v6.8 drivers/usb/core/{usb,driver,
 * message}.c. The AudioControl descriptor and entity IDs were supplied by the
 * user's EVO 16. EU58 selector meanings are an external protocol reference,
 * not a verified property of that firmware: USB stalls remain real errors.
 */

#include <linux/build_bug.h>
#include <linux/compat.h>
#include <linux/fs.h>
#include <linux/init.h>
#include <linux/miscdevice.h>
#include <linux/module.h>
#include <linux/mutex.h>
#include <linux/pm_runtime.h>
#include <linux/slab.h>
#include <linux/uaccess.h>
#include <linux/usb.h>
#include <linux/usb/audio.h>

#include "evo16_bridge_uapi.h"

#define EVO16_UAC2_CUR 1
#define EVO16_UAC2_RANGE 2
#define EVO16_TIMEOUT_MAX_MS 10000

/* Serializes our clients, but does not replace ALSA's own control locks. */
static DEFINE_MUTEX(evo16_request_lock);

struct evo16_lookup {
	u32 bus_number;
	u32 device_number;
	struct usb_device *udev;
};

static bool evo16_matches(struct usb_device *udev,
			 const struct evo16_lookup *lookup)
{
	return udev->bus &&
		le16_to_cpu(udev->descriptor.idVendor) == EVO16_USB_VENDOR_ID &&
		le16_to_cpu(udev->descriptor.idProduct) == EVO16_USB_PRODUCT_ID &&
		udev->bus->busnum == lookup->bus_number &&
		udev->devnum == lookup->device_number;
}

static int evo16_find_device(struct usb_device *udev, void *data)
{
	struct evo16_lookup *lookup = data;

	if (!evo16_matches(udev, lookup))
		return 0;
	lookup->udev = usb_get_dev(udev);
	return 1;
}

/* A RANGE request may first fetch just its two-byte subrange count. */
static bool evo16_standard_length(const struct evo16_readonly_request *req,
				 unsigned int current_length)
{
	if (req->request == EVO16_UAC2_CUR)
		return req->length == current_length;
	return req->request == EVO16_UAC2_RANGE && req->length >= 2;
}

static int evo16_validate_request(const struct evo16_readonly_request *req)
{
	if (!req->bus_number || !req->device_number || req->device_number > 127 ||
	    req->interface_number > 255 || !req->length ||
	    req->length > EVO16_READONLY_MAX_DATA || !req->timeout_ms ||
	    req->timeout_ms > EVO16_TIMEOUT_MAX_MS)
		return -EINVAL;

	if (req->request != EVO16_UAC2_CUR && req->request != EVO16_UAC2_RANGE)
		return -EOPNOTSUPP;

	switch (req->unit_id) {
	case 40: /* Clock Selector: current pin only; no clock changes. */
		if (req->selector == 1 && req->channel == 0 &&
		    req->request == EVO16_UAC2_CUR && req->length == 1)
			return 0;
		break;
	case 41: /* Internal clock. */
	case 44: /* Optical 1 clock. */
	case 45: /* Optical 2 clock. */
		if (req->channel != 0)
			break;
		if (req->selector == 1 && evo16_standard_length(req, 4))
			return 0;
		if (req->selector == 2 && req->request == EVO16_UAC2_CUR &&
		    req->length == 1)
			return 0;
		break;
	case 11: /* Feature Unit: Input Gain and Phase Inverter only. */
		if (req->channel < 1 || req->channel > 24)
			break;
		if (req->selector == 0x0b && evo16_standard_length(req, 2))
			return 0;
		if (req->selector == 0x0d && evo16_standard_length(req, 1))
			return 0;
		break;
	case 58: /* Private Input Control EU: experimental reference mapping. */
		if (req->selector <= 2 && req->channel <= 23 &&
		    req->request == EVO16_UAC2_CUR && req->length == 4)
			return 0;
		break;
	case 60: /* Mixer: 34 inputs, 6 outputs. */
	case 61: /* Mixer: 34 inputs, 4 outputs. */
		if (req->selector >= 1 && req->selector <= 34 &&
		    req->channel >= 1 &&
		    req->channel <= (req->unit_id == 60 ? 6 : 4) &&
		    evo16_standard_length(req, 2))
			return 0;
		break;
	}
	return -EOPNOTSUPP;
}

static int evo16_transfer(struct evo16_readonly_request *req)
{
	struct evo16_lookup lookup = {
		.bus_number = req->bus_number,
		.device_number = req->device_number,
	};
	struct usb_interface *intf = NULL;
	struct usb_interface_descriptor *desc;
	struct usb_device *udev;
	void *buffer;
	int ret;

	buffer = kzalloc(req->length, GFP_KERNEL);
	if (!buffer)
		return -ENOMEM;

	usb_for_each_dev(&lookup, evo16_find_device);
	udev = lookup.udev;
	if (!udev) {
		ret = -ENODEV;
		goto out_buffer;
	}

	ret = usb_lock_device_interruptible(udev);
	if (ret)
		goto out_device;

	/* A retained reference does not establish that hardware is still present. */
	if (!evo16_matches(udev, &lookup) ||
	    !device_is_registered(&udev->dev) || !udev->authorized ||
	    (udev->state != USB_STATE_CONFIGURED &&
	     udev->state != USB_STATE_SUSPENDED)) {
		ret = -ENODEV;
		goto out_unlock;
	}

	/*
	 * Same parent-device PM lifetime as usbcore's internal autoresume path.
	 * usb_autoresume_device() itself is not exported to external modules.
	 * This temporary reference preserves the existing autosuspend policy.
	 */
	ret = pm_runtime_resume_and_get(&udev->dev);
	if (ret < 0)
		goto out_unlock;

	if (udev->state != USB_STATE_CONFIGURED || !udev->actconfig) {
		ret = -ENODEV;
		goto out_pm;
	}

	intf = usb_ifnum_to_if(udev, req->interface_number);
	if (!intf) {
		ret = -ENODEV;
		goto out_pm;
	}
	usb_get_intf(intf);
	if (!device_is_registered(&intf->dev) || !intf->authorized ||
	    !intf->cur_altsetting) {
		ret = -ENODEV;
		goto out_interface;
	}
	desc = &intf->cur_altsetting->desc;
	if (desc->bInterfaceNumber != req->interface_number ||
	    desc->bInterfaceClass != USB_CLASS_AUDIO ||
	    desc->bInterfaceSubClass != USB_SUBCLASS_AUDIOCONTROL ||
	    desc->bInterfaceProtocol != UAC_VERSION_2) {
		ret = -EINVAL;
		goto out_interface;
	}

	/* Hardcoded IN/class/interface; no caller-supplied request-type byte. */
	ret = usb_control_msg(udev, usb_rcvctrlpipe(udev, 0), req->request,
			      USB_DIR_IN | USB_TYPE_CLASS | USB_RECIP_INTERFACE,
			      (req->selector << 8) | req->channel,
			      (req->unit_id << 8) | desc->bInterfaceNumber,
			      buffer, req->length, req->timeout_ms);
	if (ret >= 0) {
		if (ret > req->length) {
			ret = -EOVERFLOW;
		} else {
			req->actual_length = ret;
			memcpy(req->data, buffer, ret);
			ret = 0;
		}
	}

out_interface:
	usb_put_intf(intf);
out_pm:
	usb_mark_last_busy(udev);
	pm_runtime_put_sync_autosuspend(&udev->dev);
out_unlock:
	usb_unlock_device(udev);
out_device:
	usb_put_dev(udev);
out_buffer:
	kfree(buffer);
	return ret;
}

static long evo16_ioctl(struct file *file, unsigned int command,
			unsigned long argument)
{
	struct evo16_readonly_request *req;
	void __user *user = (void __user *)argument;
	int ret;

	if (command != EVO16_READONLY_IOCTL)
		return -ENOTTY;
	req = kzalloc(sizeof(*req), GFP_KERNEL);
	if (!req)
		return -ENOMEM;
	if (copy_from_user(req, user, sizeof(*req))) {
		ret = -EFAULT;
		goto out;
	}
	ret = evo16_validate_request(req);
	if (ret)
		goto out;
	req->actual_length = 0;
	memset(req->data, 0, sizeof(req->data));

	ret = mutex_lock_interruptible(&evo16_request_lock);
	if (ret)
		goto out;
	ret = evo16_transfer(req);
	mutex_unlock(&evo16_request_lock);
	if (!ret && copy_to_user(user, req, sizeof(*req)))
		ret = -EFAULT;
out:
	kfree(req);
	return ret;
}

static const struct file_operations evo16_fops = {
	.owner = THIS_MODULE,
	.open = nonseekable_open,
	.unlocked_ioctl = evo16_ioctl,
#ifdef CONFIG_COMPAT
	.compat_ioctl = compat_ptr_ioctl,
#endif
};

static struct miscdevice evo16_misc = {
	.minor = MISC_DYNAMIC_MINOR,
	.name = "evo16-readonly",
	.fops = &evo16_fops,
	.mode = 0600,
};

static int __init evo16_init(void)
{
	BUILD_BUG_ON(sizeof(struct evo16_readonly_request) != 4120);
	return misc_register(&evo16_misc);
}

static void __exit evo16_exit(void)
{
	misc_deregister(&evo16_misc);
}

module_init(evo16_init);
module_exit(evo16_exit);
MODULE_LICENSE("GPL");
MODULE_AUTHOR("EVOLINUX contributors");
MODULE_DESCRIPTION("Experimental read-only Audient EVO 16 UAC2 bridge");
