# player_object.py
#
# Copyright 2023 Nokse
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
# SPDX-License-Identifier: GPL-3.0-or-later

import random
import threading
from enum import IntEnum

from tidalapi.mix import Mix
from tidalapi.artist import Artist
from tidalapi.album import Album
from tidalapi.playlist import Playlist

from gi.repository import GObject
from gi.repository import Gst, GLib


class RepeatType(IntEnum):
    NONE = 0
    SONG = 1
    LIST = 2


class AudioSink(IntEnum):
    AUTO = 0
    PULSE = 1
    ALSA = 2
    JACK = 3
    OSS = 4


class PlayerObject(GObject.GObject):
    """Handles player logic, queue, and shuffle functionality."""

    shuffle_mode = GObject.Property(type=bool, default=False)
    current_song_index = GObject.Property(type=int, default=-1)
    is_playing = GObject.Property(type=bool, default=False)

    __gsignals__ = {
        'songs-list-changed': (GObject.SignalFlags.RUN_FIRST, None, (int,)),
        'update-slider': (GObject.SignalFlags.RUN_FIRST, None, ()),
        'song-changed': (GObject.SignalFlags.RUN_FIRST, None, ()),
        'song-added-to-queue': (GObject.SignalFlags.RUN_FIRST, None, ()),
        'play-changed': (GObject.SignalFlags.RUN_FIRST, None, (bool,)),
        'duration-changed': (GObject.SignalFlags.RUN_FIRST, None, ()),
        'shuffle-changed': (GObject.SignalFlags.RUN_FIRST, None, (bool,)),
        'volume-changed': (GObject.SignalFlags.RUN_FIRST, None, (float,))
    }

    # TODO add add_to_queue and play_next back!!!

    def __init__(self, preferred_sink=AudioSink.AUTO, sink_device=None):
        GObject.GObject.__init__(self)
        Gst.init()

        # Initialize player
        self._player = Gst.ElementFactory.make('playbin3', 'player')
        if not self._player:
            raise RuntimeError("Could not create playbin3 element")

        self._player.set_property('buffer-size', 2097152)
        self._player.set_property('buffer-duration', 3 * Gst.SECOND)
        self._player.set_property('low-percent', 10)
        self._player.set_property('high-percent', 99)
        self._player.set_property('max-size-buffers', 0)
        self._player.set_property('max-size-time', 0)
        self._player.set_property('max-size-bytes', 0)

        # Configure audio sink
        self._setup_audio_sink(preferred_sink, sink_device)

        # Set up message bus
        self._bus = self._player.get_bus()
        self._bus.add_signal_watch()
        self._bus.connect('message::eos', self._on_bus_eos)
        self._bus.connect('message::error', self._on_bus_error)
        self._bus.connect('message', self._on_bus_message)

        # Initialize state variables
        self.queue = []
        self.current_mix_album_playlist = None
        self._tracks_to_play = []
        self.tracks_to_play = []
        self._shuffled_tracks_to_play = []
        self.played_songs = []

        self.shuffle_mode = False
        self.is_playing = False
        self.playing_track = None
        self.song_album = None
        self.repeat = RepeatType.NONE
        self.duration = self.query_duration()
        self.can_next = False
        self.can_prev = False

    def _setup_audio_sink(self, sink_type, device):
        """Configure the audio sink based on preferences."""
        sink_map = {
            AudioSink.AUTO: 'autoaudiosink',
            AudioSink.PULSE: 'pulsesink',
            AudioSink.ALSA: 'alsasink',
            AudioSink.JACK: 'jackaudiosink',
            AudioSink.OSS: 'osssink'
        }

        sink_name = sink_map.get(sink_type, 'autoaudiosink')
        sink_element = Gst.ElementFactory.make(sink_name, 'audio_sink')

        if not sink_element:
            print(f"Could not create {sink_name}, falling back to auto")
            sink_element = Gst.ElementFactory.make(
                'autoaudiosink', 'audio_sink')
            if not sink_element:
                raise RuntimeError("Could not create audio sink")

        if device and sink_type != AudioSink.AUTO:
            sink_element.set_property('device', device)

        self._player.set_property('audio-sink', sink_element)

    def change_audio_sink(self, sink_type, device=None):
        """Change the audio sink while maintaining playback state."""
        was_playing = self.is_playing
        position = self.query_position()
        duration = self.query_duration()

        self._player.set_state(Gst.State.NULL)
        self._setup_audio_sink(sink_type, device)

        if was_playing and duration != 0:
            self._player.set_state(Gst.State.PLAYING)
            self.seek(position / duration)

    def _on_bus_eos(self, *args):
        """Handle end of stream."""
        GLib.idle_add(self.play_next)

    def _on_bus_error(self, bus, message):
        """Handle pipeline errors."""
        err, debug = message.parse_error()
        print(f"Error: {err.message}")
        print(f"Debug info: {debug}")

    def _on_bus_message(self, bus, message):
        msg_type = message.type
        msg_src = message.src.get_name()
        print(f"Got message {msg_type} from {msg_src}")

        if msg_type == Gst.MessageType.ERROR:
            err, debug = message.parse_error()
            print(f"Error: {err}, Debug: {debug}")
        elif msg_type == Gst.MessageType.WARNING:
            warn, debug = message.parse_warning()
            print(f"Warning: {warn}, Debug: {debug}")
        elif msg_type == Gst.MessageType.INFO:
            info, debug = message.parse_info()
            print(f"Info: {info}, Debug: {debug}")
        elif msg_type == Gst.MessageType.STATE_CHANGED:
            old, new, pending = message.parse_state_changed()
            print(f"State changed from {old} to {new}, Pending: {pending}")
        elif msg_type == Gst.MessageType.EOS:
            print("End of stream")
        elif msg_type == Gst.MessageType.SEGMENT_START:
            pos = message.parse_segment_start()
            print(f"Segment start: {pos}")
        elif msg_type == Gst.MessageType.SEGMENT_DONE:
            print("Segment done")
        elif msg_type == Gst.MessageType.DURATION_CHANGED:
            print("Duration changed")
        elif msg_type == Gst.MessageType.TAG:
            taglist = message.parse_tag()
            print(f"Tags: {taglist.to_string()}")
        elif msg_type == Gst.MessageType.STREAM_START:
            print("Stream started")
        elif msg_type == Gst.MessageType.ASYNC_DONE:
            print("Async operation done")
        elif msg_type == Gst.MessageType.STREAM_STATUS:
            status, owner = message.parse_stream_status()
            print(f"Stream status: {status}, Owner: {owner.get_name()}")
        elif msg_type == Gst.MessageType.APPLICATION:
            struct = message.get_structure()
            print(f"Application message: {struct.to_string()}")
        elif msg_type == Gst.MessageType.ELEMENT:
            struct = message.get_structure()
            print(f"Element message: {struct.to_string()}")
        elif msg_type == Gst.MessageType.QOS:
            live, running_time, stream_time, timestamp, duration = message.parse_qos()
            print(f"QOS: live={live}, running_time={running_time}, stream_time={stream_time}")
        elif msg_type == Gst.MessageType.PROGRESS:
            type_, code, text = message.parse_progress()
            print(f"Progress: type={type_}, code={code}, text={text}")
        elif msg_type == Gst.MessageType.TOC:
            toc, updated = message.parse_toc()
            print(f"TOC updated: {updated}")
        elif msg_type == Gst.MessageType.RESET_TIME:
            running_time = message.parse_reset_time()
            print(f"Reset time: {running_time}")
        elif msg_type == Gst.MessageType.STREAM_COLLECTION:
            collection = message.parse_stream_collection()
            print(f"Stream collection updated: {collection.get_size()} streams")
        elif msg_type == Gst.MessageType.STREAMS_SELECTED:
            collection = message.parse_streams_selected()
            print(f"Streams selected from collection: {collection.get_size()} streams")
        elif msg_type == Gst.MessageType.REDIRECT:
            location = message.get_structure().get_string("new-location")
            print(f"Redirect to: {location}")
        elif msg_type == Gst.MessageType.DEVICE_ADDED:
            device = message.parse_device_added()
            print(f"Device added: {device.get_display_name()}")
        elif msg_type == Gst.MessageType.DEVICE_REMOVED:
            device = message.parse_device_removed()
            print(f"Device removed: {device.get_display_name()}")
        elif msg_type == Gst.MessageType.PROPERTY_NOTIFY:
            obj, prop_name, val = message.parse_property_notify()
            print(f"Property notify: object={obj.get_name()}, property={prop_name}, value={val}")
        elif msg_type == Gst.MessageType.BUFFERING:
            percent = message.parse_buffering()
            print(f"Buffering: {percent}%")
        elif msg_type == Gst.MessageType.STATE_DIRTY:
            print("State dirty")
        elif msg_type == Gst.MessageType.CLOCK_LOST:
            print("Clock lost")
        elif msg_type == Gst.MessageType.CLOCK_PROVIDE:
            clock, ready = message.parse_clock_provide()
            print(f"Clock provided: {clock.get_name()}, ready: {ready}")
        elif msg_type == Gst.MessageType.NEW_CLOCK:
            clock = message.parse_new_clock()
            print(f"New clock: {clock.get_name()}")
        elif msg_type == Gst.MessageType.STRUCTURE_CHANGE:
            type_, owner, busy = message.parse_structure_change()
            print(f"Structure change: type={type_}, owner={owner.get_name()}, busy={busy}")
        elif msg_type == Gst.MessageType.REQUEST_STATE:
            state = message.parse_request_state()
            print(f"State requested: {state}")
        elif msg_type == Gst.MessageType.STEP_START:
            active, amount, rate, flush, intermediate = message.parse_step_start()
            print(f"Step start: active={active}, amount={amount}, rate={rate}")
        elif msg_type == Gst.MessageType.STEP_DONE:
            amount, rate, flush, intermediate, duration, eos = message.parse_step_done()
            print(f"Step done: amount={amount}, rate={rate}, duration={duration}")
        elif msg_type == Gst.MessageType.LATENCY:
            print("Latency changed")
        elif msg_type == Gst.MessageType.HAVE_CONTEXT:
            context = message.parse_have_context()
            print(f"Have context: {context.get_context_type()}")
        elif msg_type == Gst.MessageType.NEED_CONTEXT:
            context_type = message.parse_context_type()
            print(f"Need context: {context_type}")

    def play_this(self, thing, index=0):
        """Play tracks from a mix, album, playlist, or artist."""
        self.current_mix_album_playlist = thing
        tracks = self.get_track_list(thing)

        if not tracks:
            print("No tracks found to play")
            return

        self._tracks_to_play = tracks[index:] + tracks[:index]
        if not self._tracks_to_play:
            return

        track = self._tracks_to_play.pop(0)
        self.tracks_to_play = self._tracks_to_play
        self.played_songs = []

        self.play_track(track)
        self.play()
        self.emit("song-changed")

    def shuffle_this(self, thing):
        """Same as play_this, but on shuffle"""
        tracks = self.get_track_list(thing)
        self.play_this(tracks, random.randint(0, len(tracks)))
        self.shuffle(True)

    def get_track_list(self, thing):
        """Convert various sources into a list of tracks."""
        if isinstance(thing, Mix):
            return thing.items()
        elif isinstance(thing, Album):
            return thing.tracks()
        elif isinstance(thing, Playlist):
            return thing.tracks()
        elif isinstance(thing, Artist):
            return thing.top_tracks()
        elif isinstance(thing, list):
            return thing
        return []

    def play(self):
        """Start playback."""
        self.is_playing = True
        self.notify("is_playing")
        self.emit("play-changed", self.is_playing)
        self._player.set_state(Gst.State.PLAYING)
        GLib.timeout_add(1000, self._update_slider_callback)

    def pause(self):
        """Pause playback."""
        self.is_playing = False
        self.notify("is_playing")
        self.emit("play-changed", self.is_playing)
        self._player.set_state(Gst.State.PAUSED)

    def play_pause(self):
        """Toggle between play and pause states."""
        if self.is_playing:
            self.pause()
        else:
            self.play()

    def play_track(self, track):
        """Play a specific track."""
        threading.Thread(target=self._play_track_thread, args=(track,)).start()

    def _play_track_thread(self, track):
        """Thread for loading and playing a track."""
        try:
            music_url = track.get_url()
            GLib.idle_add(self._play_track_url, track, music_url)
        except Exception as e:
            print(f"Error getting track URL: {e}")

    def _play_track_url(self, track, music_url):
        """Set up and play track from URL."""
        self._player.set_state(Gst.State.NULL)
        self._player.set_property("uri", music_url)
        self.duration = self.query_duration()

        if self.is_playing:
            self.play()

        self.playing_track = track
        self.song_album = track.album
        self.can_next = bool(self._tracks_to_play)
        self.can_prev = bool(self.played_songs)
        self.emit("song-changed")

    def play_next(self):
        """Play the next track."""
        if self.repeat == RepeatType.SONG:
            self.seek(0)
            return

        if self.playing_track:
            self.played_songs.append(self.playing_track)

        if self.queue:
            track = self.queue.pop(0)
            self.play_track(track)
            return

        if not self._tracks_to_play and self.repeat == RepeatType.LIST:
            self._tracks_to_play = self.played_songs
            self.tracks_to_play = self._tracks_to_play
            self.played_songs = []

        if not self._tracks_to_play:
            self.pause()
            return

        track = (self._shuffled_tracks_to_play if self.shuffle_mode else self._tracks_to_play).pop(0)
        self.play_track(track)

    def play_previous(self):
        """Play the previous track."""
        if not self.played_songs:
            return

        last_index = len(self.played_songs) - 1
        track = self.played_songs.pop(last_index)
        if self.playing_track:
            self._tracks_to_play.insert(0, self.playing_track)
        self.play_track(track)

    def shuffle(self, state):
        """Enable or disable shuffle mode."""
        if self.shuffle_mode == state:
            return

        self.shuffle_mode = state
        self.emit("shuffle-changed", self.shuffle_mode)

        if state:
            self._shuffled_tracks_to_play = self._tracks_to_play.copy()
            random.shuffle(self._shuffled_tracks_to_play)
            self.tracks_to_play = self._shuffled_tracks_to_play
        else:
            self.tracks_to_play = self._tracks_to_play

        self.emit("song-changed")

    def add_to_queue(self, track):
        self.queue.append(track)
        self.emit("song-added-to-queue")

    def add_next(self, track):
        self.queue.insert(0, track)
        self.emit("song-added-to-queue")

    def change_volume(self, value):
        self._player.set_property("volume", value)
        self.emit("volume-changed", value)

    def _update_slider_callback(self):
        """Update playback slider and duration."""
        self.emit("update-slider")
        duration = self.query_duration()
        if duration != self.duration:
            self.emit("duration-changed")
        return self.is_playing

    def query_duration(self):
        """Get the duration of the current track."""
        success, duration = self._player.query_duration(Gst.Format.TIME)
        return duration if success else 0

    def query_position(self):
        """Get the current playback position."""
        success, position = self._player.query_position(Gst.Format.TIME)
        return position if success else 0

    def seek(self, seek_fraction):
        """Seek to a position in the current track."""
        self._player.seek_simple(
            Gst.Format.TIME,
            Gst.SeekFlags.FLUSH | Gst.SeekFlags.KEY_UNIT,
            int(seek_fraction * self.query_duration()))
