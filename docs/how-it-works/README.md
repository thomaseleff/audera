     ________  ___  ___  ________  _______  ________  ________     
    |\   __  \|\  \|\  \|\   ___ \|\   ___\|\   __  \|\   __  \    
    \ \  \|\  \ \  \\\  \ \  \_|\ \ \  \__|\ \  \|\  \ \  \|\  \   
     \ \   __  \ \  \\\  \ \  \ \\ \ \   __\\ \      /\ \   __  \  
      \ \  \ \  \ \  \\\  \ \  \_\\ \ \  \_|_\ \  \  \ \ \  \ \  \ 
       \ \__\ \__\ \______/\ \______/\ \______\ \__\\ _\\ \__\ \__\
        \|__|\|__|\|______| \|______| \|______|\|__|\|__|\|__|\|__|

`alpha-release` coming soon!

`audera` is an open-source multi-room audio streaming system written in Python for DIY home audio enthusiasts.

## How `audera` works
The streamer and player applications each run tasks within an asynchronous event loop.

### Streamer
The streamer service runs the following tasks,
- Network time protocol (ntp) synchronization
- Remote audio output player mDNS browsing with player connection, playback session management and multi-player synchronization
- Audio stream capturing and broadcasting

#### Event loop flow diagram
```
                                                                                                      mdns-browser              
                                                                                         tasks          +-------+                    
                                                   +-------------------+-------------------+---------+--> event +-waits-+            
                                                   |                   |                   |         |  +-------+       |            
                                                   |            +------v-----+      +------v-----+   |           +------v-----+      
                                                   |            |            |      |            |  sets         |            |      
                                                   |            |            |      |            |   |           |            |      
                                                   |            |    ntp-    |      |    mdns-   |   |           |    audio   |      
                                                   |            |synchronizer|      |   browser  +---+           |  streamer  |      
    +------------+      +------------+      +------+-----+      |            |      |            |               |            |      
    |            |      |            |      |            |      |            |      |            |               |            |      
    |            |      |            |      |            |      +------+-----+      +------+-----+               +------+-----+      
    |  streamer  |      |    event   | run  |  services  |             | every 600 sec.    | every 5 sec.               | every 0 sec.
    |            +------>    loop    +------>            <-------------+-------------------+----------------------------+            
    |            |      |            |      |            |                     until tasks are cancelled                           
    |            |      |            |      |            |                                                                         
    +------------+      +------^-----+      +------+-----+                                                                         
                               |                   |                                                                               
                               |                   |                                                                               
                               +-------------------+                                                                               
                           until event loop is cancelled                                                                           
```

#### Getting-started
The streamer service can be run from the command-line,

``` bash
audera run streamer
```

Or, through a Python session,

``` python
import asyncio
import audera

if __name__ == '__main__':
    asyncio.run(audera.streamer.Service().run())
```

### Player
A `class` that represents the `audera` remote audio output player service.

The player service runs the following tasks within an async event loop,
- Shairport-sync remote audio output player service for `airplay` connectivity
- Audera remote audio output player service for `audera` connectivity

#### Event loop flow diagram
```
                                                                     tasks                                                                                                                                
                                                   +-------------------+-------------------+                                                                                                              
                                                   |                   |                   |                                                                                                              
                                                   |            +------v-----+      +------v-----+                                                                                                        
                                                   |            |            |      |            |                                                                                                        
                                                   |            |            |      |            |                                     tasks                                                              
                                                   |            | shairport- |      |   audera   +-------------+---+----------------------------+                                                            
                                                   |            |sync player |      |   player   |             |   |                            |                                                            
    +------------+      +------------+      +------+-----+      |            |      |            |             |   |    mdns-broadcaster        |          sync                        buffer                 
    |            |      |            |      |            |      |            |      |            |             |   |        +-------+           |        +-------+                    +-------+                    
    |            |      |            |      |            |      +------+-----+      +---+----^---+             |   +-----+--> event +-waits-+   +-----+--> event +-waits-+---------+--> event +-waits-+            
    |   player   |      |    event   | run  |  services  |             | every 5 sec.   |    |                 |         |  +-------+       |         |  +-------+       |         |  +-------+       |            
    |            +------>    loop    +------>            <-------------+----------------+    |          +------v-----+   |           +------v-----+   |           +------v-----+   |           +------v-----+      
    |            |      |            |      |            |   until tasks are cancelled       |          |            |  sets         |            |  sets         |            |  sets         |            |      
    |            |      |            |      |            |                                   |          |            |   |           |            |   |           |            |   |           |            |      
    +------------+      +------^-----+      +------+-----+                                   |          |    mdns-   |   |           |  streamer- |   |           |   audio-   |   |           |   audio    |      
                               |                   |                                         |          |   browser  +---+           |synchronizer+---+           |  receiver  +---+           |   player   |      
                               |                   |                                         |          |            |               |            |               |            |               |            |      
                               +-------------------+                                         |          |            |               |            |               |            |               |            |      
                           until event loop is cancelled                                     |          +------+-----+               +------+-----+               +------+-----+               +------+-----+      
                                                                                             |                 | every 5 sec.               | continuous                 | continuous                 |
                                                                                             +-----------------+----------------------------+----------------------------+----------------------------+                                                                                   
```

#### Getting-started
The player service can be run from the command-line,

``` bash
audera run player
```

Or, through a Python session,

``` python
import asyncio
import audera

if __name__ == '__main__':
    asyncio.run(audera.player.Service().run())
```