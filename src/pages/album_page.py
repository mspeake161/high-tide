from gi.repository import Adw
from gi.repository import Gtk
from gi.repository import GLib
from gi.repository import Gio
from gi.repository import Gdk

import tidalapi
from tidalapi.page import PageItem, PageLink
from tidalapi.mix import Mix, MixType
from tidalapi.artist import Artist
from tidalapi.album import Album
from tidalapi.media import Track
from tidalapi.playlist import Playlist

from ..lib import utils

import threading
import requests
import random

from .page import Page

class albumPage(Page):
    __gtype_name__ = 'albumPage'

    def _load_page(self):
        builder = Gtk.Builder.new_from_resource("/io/github/nokse22/high-tide/ui/pages_ui/tracks_list_template.ui")

        page_content = builder.get_object("_main")
        tracks_list_box = builder.get_object("_list_box")
        tracks_list_box.connect("row-selected", self.on_row_selected)

        builder.get_object("_title_label").set_label(self.item.name)
        builder.get_object("_first_subtitle_label").set_label(self.item.artist.name)
        builder.get_object("_second_subtitle_label").set_label(f"{self.item.num_tracks} tracks ({utils.pretty_duration(self.item.duration)})")

        builder.get_object("_play_button").connect("clicked", self.on_play_button_clicked)
        builder.get_object("_shuffle_button").connect("clicked", self.on_shuffle_button_clicked)

        for index, track in enumerate(self.item.items()):
            listing = self.get_album_track_listing(track)
            listing.set_name(str(index))
            tracks_list_box.append(listing)

        self.content.remove(self.spinner)
        self.content.append(page_content)
