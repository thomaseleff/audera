     ________  ___  ___  ________  _______  ________  ________     
    |\   __  \|\  \|\  \|\   ___ \|\   ___\|\   __  \|\   __  \    
    \ \  \|\  \ \  \\\  \ \  \_|\ \ \  \__|\ \  \|\  \ \  \|\  \   
     \ \   __  \ \  \\\  \ \  \ \\ \ \   __\\ \      /\ \   __  \  
      \ \  \ \  \ \  \\\  \ \  \_\\ \ \  \_|_\ \  \  \ \ \  \ \  \ 
       \ \__\ \__\ \______/\ \______/\ \______\ \__\\ _\\ \__\ \__\
        \|__|\|__|\|______| \|______| \|______|\|__|\|__|\|__|\|__|

`alpha-release` coming soon!

`audera` is an open-source multi-room audio streaming system written in Python for DIY home audio enthusiasts.

## Getting-started
Check out the `audera` docs for more information on the types of deployment architectures and details on how the streamer and player applications work.

- [Deployment architectures](./docs/deployment-architectures/README.md)
- [How-it-works](./docs/how-it-works/README.md)

## Installation
The source code is available on [GitHub](https://github.com/thomaseleff/audera).

`audera` can be installed via Github from the command-line.

1. Setup a Python developer environment. `audera` supports Python versions >= 3.11.
2. From the command-line, run,

   ```
   # Via Github
   git clone -b main https://github.com/thomaseleff/audera.git
   ```

3. Navigate into the cloned repository directory and install via pip,

   ```
   pip install .
   ```

## Roadmap
Upcoming enhancements / fixes in priority order. Open an [issue](https://github.com/thomaseleff/audera/issues/new) to request a feature or fix.

- [x] Access point Wi-Fi sharing
- [ ] Digital sound processing (DSP)
- [ ] Audera streamer (Bluetooth input-only)
- [ ] Audera streamer Wi-Fi sharing setup
- [ ] Audera streamer web-interface
  - [ ] Managing players / player groups and playback sessions
  - [ ] Streamer settings
  - [ ] Danger zone OTT updates

#### Misc. improvements
- [ ] FLAC encoding / decoding with ffmpeg
- [ ] Multi-player sync optimization
- [ ] Event tracking (logins / sessions / errors, etc..)