# Transferência dos fontes recuperados 0.3.1

Este diretório contém o ZIP exato solicitado para transferência, com somente
EVOLINUX-0.3.1-recovered.bundle em seu interior. Os fontes originais e seus
commits permanecem preservados na branch codex/evo16-native-controller.
Esta branch de transferência acrescenta apenas estes arquivos de entrega.

ZIP: 179008 bytes; SHA-256:
d0cdf8f0299d2bc5c5663d251b5d4983a26f7bd516355f10b23822e4661f5e67

Bundle dentro do ZIP: 179040 bytes; SHA-256:
36e7a897d0544ea64aad796b9df9dd76321f9450f66e05046bfc7abb5e2c48c5

O bundle autossuficiente contém seis commits e 67 arquivos na árvore final.
Seu HEAD é c8c89b61add0b4bcb6c8d1696fab6b8f2c2d0234. O runtime é 0.3.1;
esta entrega não contém a GUI 0.5.1. Nenhum fonte foi recriado.

Para conferir o ZIP baixado nesta pasta:

```bash
sha256sum --check EVOLINUX-0.3.1-recovered-bundle.zip.sha256
```

Confira também o hash do bundle após a extração. Para importar, execute em
uma pasta de transferência própria, preservando quaisquer arquivos existentes:

```bash
git clone --branch codex/evo16-native-controller ./EVOLINUX-0.3.1-recovered.bundle EVOLINUX-0.3.1-recuperado
```

A transferência não executa comandos de controle ALSA/USB, módulos ou firmware.
