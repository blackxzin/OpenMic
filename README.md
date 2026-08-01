# OpenMic 🇺🇸

Turn your Android or iPhone into a wireless microphone for Linux over your WiFi network — an actively maintained alternative to WoMic and AudioRelay.

- **Desktop app** (Linux only): creates a virtual microphone and receives the audio stream from your phone.
- **Mobile app** (Android and iOS): captures your phone's microphone and streams it to the desktop app.

The two apps find each other automatically on the same WiFi network (no need to type an IP address), though you can still enter one manually if automatic discovery doesn't work on your network.

## Installing on Linux

### AppImage (works on any distro)

An AppImage is a single file that bundles the app and everything it needs — no installation, no package manager required. Download `OpenMic-x86_64.AppImage` from the [Releases page](../../releases), then:

```bash
chmod +x OpenMic-x86_64.AppImage
./OpenMic-x86_64.AppImage
```

Or just make it executable from your file manager's "Properties" dialog and double-click it.

AppImages need FUSE to run. Most distros have it out of the box, but a few need one extra step first:

| Distro family                             | What to do                                                        |
|--------------------------------------------|--------------------------------------------------------------------|
| Ubuntu 22.04+ / Linux Mint 21+ / Pop!\_OS 22.04+ | `sudo apt install libfuse2t64` (or `libfuse2` on older releases) |
| Debian, older Ubuntu/Mint                  | Usually works out of the box                                       |
| Fedora / RHEL / CentOS / Nobara            | `sudo dnf install fuse fuse-libs`                                   |
| Arch / Manjaro / EndeavourOS                | `sudo pacman -S fuse2`                                              |
| openSUSE                                   | `sudo zypper install fuse`                                          |

If you'd rather not install FUSE at all, run the AppImage in extract-and-run mode instead:

```bash
./OpenMic-x86_64.AppImage --appimage-extract-and-run
```

**Audio backend:** OpenMic creates the virtual microphone through PipeWire's PulseAudio compatibility layer (`pactl`). This ships by default on current Ubuntu, Fedora, and Arch — if your distro still uses plain PulseAudio (no PipeWire), the app needs `pactl` on your `PATH`, which PulseAudio also provides, so it should still work.

## Installing on Android / iOS

Android APKs are published on the [Releases page](../../releases) — download and install `OpenMic.apk` (you'll need to allow installing from unknown sources, since it isn't on the Play Store).

iOS isn't distributed yet — see the open issues for status.

---

# OpenMic 🇧🇷

Transforme seu Android ou iPhone em um microfone sem fio para o Linux pela sua rede WiFi — uma alternativa ao WoMic e AudioRelay mantida ativamente.

- **App desktop** (só Linux): cria um microfone virtual e recebe o áudio transmitido pelo celular.
- **App mobile** (Android e iOS): captura o microfone do celular e transmite para o app desktop.

Os dois apps se encontram automaticamente na mesma rede WiFi (sem precisar digitar IP), mas ainda dá pra digitar um manualmente caso a descoberta automática não funcione na sua rede.

## Instalando no Linux

### AppImage (funciona em qualquer distro)

Um AppImage é um único arquivo que já vem com o app e tudo que ele precisa — sem instalação, sem depender de gerenciador de pacotes. Baixe o `OpenMic-x86_64.AppImage` na [página de Releases](../../releases) e depois:

```bash
chmod +x OpenMic-x86_64.AppImage
./OpenMic-x86_64.AppImage
```

Ou simplesmente marque como executável pelas propriedades do arquivo no seu gerenciador de arquivos e dê dois cliques.

AppImages precisam do FUSE pra rodar. A maioria das distros já vem com ele, mas algumas precisam de um passo extra antes:

| Família da distro                           | O que fazer                                                        |
|--------------------------------------------|--------------------------------------------------------------------|
| Ubuntu 22.04+ / Linux Mint 21+ / Pop!\_OS 22.04+ | `sudo apt install libfuse2t64` (ou `libfuse2` em versões mais antigas) |
| Debian, Ubuntu/Mint mais antigos           | Geralmente já funciona sem fazer nada                               |
| Fedora / RHEL / CentOS / Nobara            | `sudo dnf install fuse fuse-libs`                                   |
| Arch / Manjaro / EndeavourOS                | `sudo pacman -S fuse2`                                              |
| openSUSE                                   | `sudo zypper install fuse`                                          |

Se preferir não instalar o FUSE, dá pra rodar o AppImage em modo de extração-e-execução:

```bash
./OpenMic-x86_64.AppImage --appimage-extract-and-run
```

**Backend de áudio:** o OpenMic cria o microfone virtual através da camada de compatibilidade PulseAudio do PipeWire (`pactl`). Isso já vem por padrão no Ubuntu, Fedora e Arch atuais — se sua distro ainda usa PulseAudio puro (sem PipeWire), o app só precisa do `pactl` disponível no `PATH`, que o PulseAudio também fornece, então deve funcionar do mesmo jeito.

## Instalando no Android / iOS

Os APKs do Android são publicados na [página de Releases](../../releases) — baixe e instale o `OpenMic.apk` (você vai precisar permitir instalação de fontes desconhecidas, já que não está na Play Store).

O iOS ainda não é distribuído — veja as issues abertas pra acompanhar o status.
