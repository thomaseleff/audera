""" Remote audio output player setup """

from typing_extensions import Union
from nicegui import app, ui

import audera


class Page():
    """ A `class` that represents a player setup page.

    Parameters
    ----------
    identity: `audera.struct.identity.Identity`
        An instance of an `audera.struct.identity.Identity` object.
    """

    def __init__(self, identity: audera.struct.identity.Identity):
        """ Initializes an instance of the `audera` player setup page.

        Parameters
        ----------
        identity: `audera.struct.identity.Identity`
            An instance of an `audera.struct.identity.Identity` object.
        """

        # Initialize player

        # The `update` method will either get the existing player, create a new player or
        #   update an existing player from the identity.

        self.player: audera.struct.player.Player = audera.dal.players.update(
            audera.struct.player.Player.from_config(
                audera.dal.players.get_or_create(identity)
            )
        )

        # Initialize connected network ssid
        self.connected_profile: Union[str, None] = None

        # Initialize available networks
        self.network_refreshing: bool = False

    @property
    def name(self):
        return str(self.player.name)

    def update_player_name_callback(self, name: Union[str, None]):
        """ Updates the name of the remote audio output player.

        Parameters
        ----------
        name: `Union[str, None]`
            The new name of the remote audio output player.
        """
        if name and name != self.player.name:
            self.player = audera.dal.players.update_player_name(self.player, str(name))
            ui.notify('Player name updated.', position='top-right', type='positive')

    async def connect_callback(self, ssid: str, password: str):
        """ Connects to an available Wi-Fi network and checks for a valid internet connection.

        Parameters
        ----------
        ssid: `str`
            The name of the wi-fi network.
        password: `str`
            The password of the wi-fi network.
        """

        # Start
        self.network_refreshing = True

        if not ssid:
            ui.notify(
                'Enter a network.',
                position='top-right',
                type='negative'
            )

        else:
            try:
                await audera.netifaces.connect(ssid, password)
                self.connected_profile = ssid
                ui.notify(
                    'Network `%s` connected successfully.' % ssid,
                    position='top-right',
                    type='positive'
                )

            except OSError:
                ui.notify(
                    'Network setup is unavailable.',
                    position='top-right',
                    type='negative'
                )

            except audera.netifaces.NetworkConnectionError:
                ui.notify(
                    'Unable to connect to `%s`.' % ssid,
                    position='top-right',
                    type='negative'
                )

            except audera.netifaces.InternetConnectionError:
                ui.notify(
                    '`%s` has no internet.' % ssid,
                    position='top-right',
                    type='negative'
                )

            except audera.netifaces.NetworkTimeoutError:
                ui.notify(
                    '`%s` is inaccessible.' % ssid,
                    position='top-right',
                    type='negative'
                )

            except audera.netifaces.NetworkNotFoundError:
                ui.notify(
                    '`%s` is unavailable.' % ssid,
                    position='top-right',
                    type='negative'
                )

        # Stop
        self.network_refreshing = False

    def load(self):
        """ Returns the page content. """
        ui.page('/', title='%s \u2014 👋 Welcome' % audera.NAME.lower())(self.welcome)
        ui.page('/discover', title='%s \u2014 Discover' % audera.NAME.lower())(self.discover)
        ui.page('/setup', title='%s \u2014 Setup' % audera.NAME.lower())(self.setup)
        ui.page('/connect', title='%s \u2014 Connect' % audera.NAME.lower())(self.connect)
        ui.page('/finish', title='%s \u2014 Finish' % audera.NAME.lower())(self.finish)

    def welcome(self):
        """ Returns the welcome page content. """

        with ui.row().classes("flex w-full"):
            ui.label('%s \u2014 👋 Welcome' % audera.NAME.lower()).classes('self-center text-sm ml-3')
            ui.icon("circle", size=".7rem", color='primary').classes("self-center ml-auto")
            ui.icon("circle", size=".7rem", color='gray-100').classes("self-center")
            ui.icon("circle", size=".7rem", color='gray-100').classes("self-center")
            ui.icon("circle", size=".7rem", color='gray-100').classes("self-center")
            ui.icon("circle", size=".7rem", color='gray-100').classes("self-center mr-3")

        # Welcome
        with ui.card().classes("mx-auto flex w-full"):
            ui.markdown("Welcome to **audera**").classes("text-3xl")
            ui.markdown(audera.DESCRIPTION.replace('`', '**'))
            ui.markdown('Click **Continue** to connect to your player.')

            with ui.row().classes("flex w-full"):
                ui.button(
                    'Continue',
                    on_click=lambda: ui.navigate.to('/discover')
                ).props('rounded').classes("ml-auto normal-case")

    def discover(self):
        """ Returns the discover page content. """

        with ui.row().classes("flex w-full"):
            ui.label('%s \u2014 Discover' % audera.NAME.lower()).classes('self-center text-sm ml-3')
            ui.icon("circle", size=".7rem", color='gray-100').classes("self-center ml-auto")
            ui.icon("circle", size=".7rem", color='primary').classes("self-center")
            ui.icon("circle", size=".7rem", color='gray-100').classes("self-center")
            ui.icon("circle", size=".7rem", color='gray-100').classes("self-center")
            ui.icon("circle", size=".7rem", color='gray-100').classes("self-center mr-3")

        # Discover
        with ui.card().classes("flex mx-auto w-full"):
            ui.markdown(
                "✨ Your **audera** remote audio output player connected successfully"
            ).classes("text-3xl")

            with ui.card().classes("mx-auto flex w-full"):
                with ui.row().classes("flex items-center justify-center"):
                    ui.icon("sym_r_speaker", size='lg').classes("text-lg")
                    ui.chip(
                        icon='sym_r_cast_connected',
                        color='gray-200'
                    ).bind_text_from(self, 'name').classes("font-md")

            with ui.row().classes("flex w-full"):
                ui.button('Back', on_click=lambda: ui.navigate.to('/')).props('flat rounded').classes("normal-case")
                ui.button('Setup', on_click=lambda: ui.navigate.to('/setup')).props('rounded').classes("ml-auto normal-case")

    def setup(self):
        """ Returns the setup page content. """

        with ui.row().classes("flex w-full"):
            ui.label('%s \u2014 Setup' % audera.NAME.lower()).classes('self-center text-sm ml-3')
            ui.icon("circle", size=".7rem", color='gray-100').classes("self-center ml-auto")
            ui.icon("circle", size=".7rem", color='gray-100').classes("self-center")
            ui.icon("circle", size=".7rem", color='primary').classes("self-center")
            ui.icon("circle", size=".7rem", color='gray-100').classes("self-center")
            ui.icon("circle", size=".7rem", color='gray-100').classes("self-center mr-3")

        # Setup
        with ui.card().classes("mx-auto flex w-full"):
            ui.markdown("Where is your player?").classes("text-3xl")
            ui.markdown("Naming your **audera** player will help organize your players for playback sessions and player groups.")
            ui.input(
                placeholder='Name',
                value=str(self.player.name),
                autocomplete=[
                    "Living Room",
                    "Kitchen",
                    "Bedroom",
                    "Bathroom",
                    "Dining Room",
                    "Office",
                    "Laundry Room",
                    "Hallway",
                    "Garage",
                    "Guest Room",
                    "Basement",
                    "Utility Room"
                ],
                validation={
                    "The player name cannot be empty.": lambda value: value is not None
                }
            ).props('clearable rounded-md outlined dense').classes('w-full').on(
                'blur',
                lambda event: self.update_player_name_callback(event.sender.value)
            ).on(
                'keyboard.enter',
                lambda event: self.update_player_name_callback(event.sender.value)
            ).on(
                'keyboard.down',
                lambda event: self.update_player_name_callback(event.sender.value)
            )

            with ui.row().classes("flex w-full"):
                ui.button(
                    'Back',
                    on_click=lambda: ui.navigate.to('/discover')
                ).props('flat rounded').classes("normal-case")
                ui.button(
                    'Continue',
                    on_click=lambda: ui.navigate.to('/connect')
                ).props('rounded').classes("ml-auto normal-case")

    def connect(self):
        """ Returns the connect page content. """

        with ui.row().classes("flex w-full"):
            ui.label('%s \u2014 Connect' % audera.NAME.lower()).classes('self-center text-sm ml-3')
            ui.icon("circle", size=".7rem", color='gray-100').classes("self-center ml-auto")
            ui.icon("circle", size=".7rem", color='gray-100').classes("self-center")
            ui.icon("circle", size=".7rem", color='gray-100').classes("self-center")
            ui.icon("circle", size=".7rem", color='primary').classes("self-center")
            ui.icon("circle", size=".7rem", color='gray-100').classes("self-center mr-3")

        # Connect
        with ui.card().classes("mx-auto flex w-full"):
            ui.markdown(
                "Connect to Wi-Fi"
            ).classes("text-3xl")
            ui.markdown(
                "Input the credentials for the Wi-Fi network you would like to use with your **audera** player."
            )

            self.password_selector = ui.switch(
                '🔒',
                value=True
            ).classes("ml-auto")

            with ui.card().classes("mx-auto flex w-full"):

                self.network_input = ui.input(
                    placeholder="Network",
                ).props('clearable rounded-md outlined dense').classes("w-full")

                self.password_input = ui.input(
                    placeholder="Password",
                    password=True,
                    password_toggle_button=True
                ).bind_visibility_from(
                    self,
                    'password_selector',
                    backward=lambda password_selector: password_selector.value
                ).props('clearable rounded-md outlined dense').classes("w-full")

                with ui.row().classes("flex w-full"):
                    ui.button(
                        "Connect",
                        on_click=lambda: self.connect_callback(
                            self.network_input.value,
                            self.password_input.value
                        )
                    ).props('rounded').classes("normal-case")
                    ui.spinner(size='md').bind_visibility_from(
                        self,
                        'network_refreshing'
                    )

            with ui.row().classes("flex w-full"):
                ui.button('Back', on_click=lambda: ui.navigate.to('/setup')).props('flat rounded').classes("normal-case")
                ui.button(
                    "Continue",
                    on_click=lambda: ui.navigate.to('/finish')
                ).bind_enabled_from(
                    self,
                    'connected_profile',
                    backward=lambda enabled: True if enabled else False
                ).props('rounded').classes("ml-auto normal-case")

    def finish(self):
        """ Returns the finish page content. """

        with ui.row().classes("flex w-full"):
            ui.label('%s \u2014 Finish' % audera.NAME.lower()).classes('self-center text-sm ml-3')
            ui.icon("circle", size=".7rem", color='gray-100').classes("self-center ml-auto")
            ui.icon("circle", size=".7rem", color='gray-100').classes("self-center")
            ui.icon("circle", size=".7rem", color='gray-100').classes("self-center")
            ui.icon("circle", size=".7rem", color='gray-100').classes("self-center")
            ui.icon("circle", size=".7rem", color='primary').classes("self-center mr-3")

        # Finish
        with ui.card().classes("mx-auto flex w-full"):
            ui.markdown("🎉 Your player was setup successfully").classes("text-3xl")
            ui.markdown(
                """
                Click **Finish** below to start listening.
                """
            )
            ui.markdown(
                """
                Once your player restarts, connect to your **audera** streamer to start a playback session, or,
                cast directly to your player through any AirPlay enabled device.
                """
            )
            ui.markdown(
                """
                To learn more about the **audera** ecosystem, check out the [Github](%s).
                """ % (audera.HOME)
            )

            with ui.row().classes("flex w-full"):
                ui.button(
                    'Back',
                    on_click=lambda: ui.navigate.to('/connect')
                ).props('flat rounded').classes("normal-case")
                ui.button("Finish", on_click=app.shutdown).props('rounded').classes("ml-auto normal-case")


if __name__ in ["__main__", "__mp_main__"]:

    # Initialize identity

    # The `update` method will either get the existing identity, create a new identity or
    #   update the existing identity with new network interface settings. Unlike other
    #   `audera` structure objects, where equality is based on every object attribute,
    #   identities are only considered to be the same if they share the same uuid and
    #   mac address. Finally, the name of an identity is immutable, when an identity is updated
    #   the same name is always retained.

    mac_address = audera.netifaces.get_local_mac_address()
    try:
        player_ip_address = audera.netifaces.get_local_ip_address()
    except audera.netifaces.NetworkConnectionError:
        player_ip_address = ''

    identity: audera.struct.identity.Identity = audera.dal.identities.update(
        audera.struct.identity.Identity(
            name=audera.struct.identity.generate_cool_name(),
            uuid=audera.struct.identity.generate_uuid_from_mac_address(mac_address),
            mac_address=mac_address,
            address=player_ip_address
        )
    )

    if not audera.netifaces.connected():

        # Create an access point based on the player identity
        ap = audera.ap.AccessPoint(
            name=audera.NAME,
            identity=identity
        )

        try:
            ap.start()
        except audera.ap.AccessPointError:
            raise audera.ap.AccessPointError('Access-point setup is only available on Linux.')

    # Initialize the ui
    page = Page(identity)

    # Load the page content
    page.load()

    # Run the app
    try:
        ui.run(
            title=audera.NAME.strip().lower(),
            show=False,
            reload=False
        )
    except KeyboardInterrupt:
        app.shutdown()
