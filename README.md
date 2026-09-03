# English Tutorial OpenMic 🇺🇸

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Tests](../../actions/workflows/tests.yml/badge.svg)](../../actions/workflows/tests.yml)

Turn your Android or iPhone into a wireless microphone for Linux over your WiFi network — an actively maintained alternative to WoMic and AudioRelay.

- **Desktop app** (Linux only): creates a virtual microphone and receives the audio stream from your phone.
- **Mobile app** (Android and iOS): captures your phone's microphone and streams it to the desktop app.

The two apps find each other automatically on the same WiFi network (no need to type an IP address), though you can still enter one manually if automatic discovery doesn't work on your network.

Both apps follow your system language — Portuguese or English.

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

The AppImage bundles the two libraries it loads at runtime (libopus for audio decoding and PortAudio for playback), so you don't need to install them yourself.

### Debian / Ubuntu package

A `.deb` is published on the [Releases page](../../releases) alongside the AppImage. It installs to `/opt/openmic`, adds a launcher entry, and pulls in `libopus0`, `libportaudio2` and `pulseaudio-utils` through your package manager:

```bash
sudo apt install ./openmic_*_amd64.deb
```

### Arch Linux

A `PKGBUILD` lives in [`desktop/packaging/aur`](desktop/packaging/aur). It runs the app from source against Arch's own Python packages instead of a bundled copy:

```bash
cd desktop/packaging/aur
makepkg -si
```

It needs `python-opuslib` from the AUR (`yay -S python-opuslib`, or build it the same way) — without it the desktop can't decode the phone's audio.

### Running in the background

The desktop app registers itself in your system's app launcher the first time it runs (no manual setup). Closing its window minimizes it to the system tray instead of quitting — the server and any connected phone keep running. Right-click the tray icon (or use the "Sair" menu item) to actually quit. Check "Iniciar com o sistema" in the app to have it launch automatically on login.

If your desktop environment has no system tray (some minimal Wayland setups), closing the window quits the app normally instead.

## Installing on Android / iOS

Android APKs are published on the [Releases page](../../releases) — download and install `OpenMic.apk` (you'll need to allow installing from unknown sources, since it isn't on the Play Store).

While streaming, the Android app shows a persistent "OpenMic ativo" notification. This isn't optional — it runs a foreground service so Android doesn't suspend microphone capture when you lock your screen or switch apps. It goes away when you disconnect.

iOS isn't distributed yet: signing and TestFlight need a paid Apple Developer account, which this project doesn't have. CI compiles the iOS app on every push, and you can build and install it yourself from a Mac with a free Apple ID — see [docs/ios-sideload.md](docs/ios-sideload.md).

## While you're connected

- **Audio quality**: the phone offers 16, 24 (default) and 48 kbps. Lower survives a congested network; higher sounds better when the WiFi can carry it. Your choice is remembered.
- **Connection quality**: the desktop app shows live bandwidth, packet loss, jitter and buffer depth — that's how you tell "the WiFi is bad" apart from "the microphone is bad".
- **Dropouts**: audio frames are played in sequence order with a 60 ms buffer, so reordered packets still land in place and a lost frame is reconstructed by the codec instead of clicking.
- **Only your phone**: the desktop accepts audio exclusively from a device that completed pairing, so nothing else on the WiFi can push sound into your virtual microphone.

## Developing

```bash
# Desktop (Linux)
cd desktop
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt pytest
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest      # tests
.venv/bin/python main.py                                  # run it

# Mobile
cd mobile
flutter pub get
flutter test
flutter analyze
```

The protocol between the two apps is documented in [docs/protocol.md](docs/protocol.md). Both test suites run on every push and pull request.

---

# Tutorial Português OpenMic 🇧🇷

Transforme seu Android ou iPhone em um microfone sem fio para o Linux pela sua rede WiFi — uma alternativa ao WoMic e AudioRelay mantida ativamente.

- **App desktop** (só Linux): cria um microfone virtual e recebe o áudio transmitido pelo celular.
- **App mobile** (Android e iOS): captura o microfone do celular e transmite para o app desktop.

Os dois apps se encontram automaticamente na mesma rede WiFi (sem precisar digitar IP), mas ainda dá pra digitar um manualmente caso a descoberta automática não funcione na sua rede.

Os dois apps seguem o idioma do sistema — português ou inglês.

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

O AppImage já inclui as duas bibliotecas que ele carrega em tempo de execução (libopus para decodificar o áudio e PortAudio para tocar), então você não precisa instalar nada disso.

### Pacote Debian / Ubuntu

Um `.deb` é publicado na [página de Releases](../../releases) junto com o AppImage. Ele instala em `/opt/openmic`, cria o atalho no menu e resolve `libopus0`, `libportaudio2` e `pulseaudio-utils` pelo seu gerenciador de pacotes:

```bash
sudo apt install ./openmic_*_amd64.deb
```

### Arch Linux

Tem um `PKGBUILD` em [`desktop/packaging/aur`](desktop/packaging/aur). Ele roda o app direto do código, usando os pacotes Python do próprio Arch em vez de uma cópia embutida:

```bash
cd desktop/packaging/aur
makepkg -si
```

Precisa do `python-opuslib` do AUR (`yay -S python-opuslib`, ou compile do mesmo jeito) — sem ele o desktop não consegue decodificar o áudio do celular.

### Rodando em segundo plano

O app desktop se registra sozinho no menu de aplicativos do sistema na primeira vez que roda (sem configuração manual). Fechar a janela minimiza pra bandeja do sistema em vez de sair — o servidor e qualquer celular conectado continuam rodando. Clique com o botão direito no ícone da bandeja (ou use "Sair" no menu) pra realmente encerrar. Marque "Iniciar com o sistema" no app pra ele abrir sozinho no login.

Se o seu ambiente desktop não tiver bandeja do sistema (alguns setups mínimos de Wayland), fechar a janela encerra o app normalmente.

## Instalando no Android / iOS

Os APKs do Android são publicados na [página de Releases](../../releases) — baixe e instale o `OpenMic.apk` (você vai precisar permitir instalação de fontes desconhecidas, já que não está na Play Store).

Enquanto transmite, o app Android mostra uma notificação persistente "OpenMic ativo". Isso não é opcional — ela roda um serviço em foreground pra o Android não suspender a captura do microfone quando você trava a tela ou troca de app. Some quando você desconecta.

O iOS ainda não é distribuído: assinar e publicar no TestFlight exige conta paga de Apple Developer, que o projeto não tem. O CI compila o app iOS em todo push, e você mesmo pode instalar pelo Mac com um Apple ID gratuito — veja [docs/ios-sideload.md](docs/ios-sideload.md).

## Enquanto estiver conectado

- **Qualidade do áudio**: o celular oferece 16, 24 (padrão) e 48 kbps. Menor aguenta rede congestionada; maior soa melhor quando o WiFi dá conta. A escolha fica salva.
- **Qualidade da conexão**: o app do computador mostra banda, perda de pacotes, jitter e profundidade do buffer ao vivo — é assim que você separa "o WiFi está ruim" de "o microfone está ruim".
- **Cortes no áudio**: os quadros são tocados em ordem de sequência com 60 ms de buffer, então pacote fora de ordem ainda cai no lugar certo e quadro perdido é reconstruído pelo codec em vez de dar estalo.
- **Só o seu celular**: o computador aceita áudio exclusivamente de um aparelho que concluiu o emparelhamento, então nada mais na rede consegue empurrar som pro seu microfone virtual.

## Desenvolvendo

```bash
# Desktop (Linux)
cd desktop
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt pytest
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest      # testes
.venv/bin/python main.py                                  # rodar

# Mobile
cd mobile
flutter pub get
flutter test
flutter analyze
```

O protocolo entre os dois apps está documentado em [docs/protocol.md](docs/protocol.md). Os dois conjuntos de testes rodam em todo push e pull request.
