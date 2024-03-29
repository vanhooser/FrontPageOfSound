#!/usr/bin/python

# Audio Tools, a module and set of tools for manipulating audio data
# Copyright (C) 2007-2014  Brian Langenberger

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301  USA


def digit_sum(i):
    """returns the sum of all digits for the given integer"""

    return sum(map(int, str(i)))


class DiscID(object):
    def __init__(self, offsets, total_length, track_count):
        """offsets is a list of track offsets, in CD frames
        total_length is the total length of the disc, in seconds
        track_count is the total number of tracks on the disc"""

        assert(len(offsets) == track_count)
        for o in offsets:
            assert(o >= 0)

        self.offsets = offsets
        self.total_length = total_length
        self.track_count = track_count

    @classmethod
    def from_cddareader(cls, cddareader):
        """given a CDDAReader object, returns a DiscID for that object"""

        offsets = cddareader.track_offsets
        return cls(offsets=[(offsets[k] // 588) + 150 for k in
                            sorted(offsets.keys())],
                   total_length=((cddareader.last_sector // 75) -
                                 (cddareader.first_sector // 75)),
                   track_count=len(offsets))

    @classmethod
    def from_tracks(cls, tracks):
        """given a sorted list of tracks,
        returns DiscID for those tracks as if they were a CD"""

        offsets = [150]
        for track in tracks[0:-1]:
            offsets.append(offsets[-1] + track.cd_frames())

        return cls(offsets=offsets,
                   total_length=sum([t.cd_frames() for t in tracks]) // 75,
                   track_count=len(tracks))

    @classmethod
    def from_sheet(cls, sheet, total_pcm_frames, sample_rate):
        """given a Sheet object
        length of the album in PCM frames
        and sample rate of the disc,
        returns a DiscID for that CD"""

        return cls(offsets=[int(t.index(1).offset() * 75 + 150)
                            for t in sheet],
                   total_length=((total_pcm_frames // sample_rate) -
                                 int(sheet.track(1).index(1).offset())),
                   track_count=len(sheet))

    def __repr__(self):
        return "DiscID(%s)" % \
            ", ".join(["%s=%s" % (attr, getattr(self, attr))
                       for attr in ["offsets",
                                    "total_length",
                                    "track_count"]])

    def __str__(self):
        return "%8.8X" % (int(self))

    def __int__(self):
        digit_sum_ = sum([digit_sum(o // 75) for o in self.offsets])
        return (((digit_sum_ % 255) << 24) |
                ((self.total_length & 0xFFFF) << 8) |
                (self.track_count & 0xFF))


def perform_lookup(disc_id, freedb_server, freedb_port):
    """performs a web-based lookup using a DiscID
    on the given freedb_server string and freedb_int port

    iterates over a list of MetaData objects per successful match, like:
    [track1, track2, ...], [track1, track2, ...], ...

    may raise urllib2.HTTPError if an error occurs querying the server
    or ValueError if the server returns invalid data
    """

    import re
    from socket import getfqdn
    from urllib2 import urlopen
    from urllib import urlencode
    from itertools import izip
    from time import sleep
    from audiotools import VERSION

    RESPONSE = re.compile(r'(\d{3}) (.+?)[\r\n]+')
    QUERY_RESULT = re.compile(r'(\S+) ([0-9a-fA-F]{8}) (.+)')
    FREEDB_LINE = re.compile(r'(\S+?)=(.+?)[\r\n]+')

    # perform initial FreeDB query
    # and get a list of category/disc id/title results
    # if any matches are found
    m = urlopen("http://%s:%d/~cddb/cddb.cgi" % (freedb_server, freedb_port),
                urlencode({"hello": "user %s %s %s" %
                           (getfqdn(),
                            "audiotools",
                            VERSION),
                           "proto": str(6),
                           "cmd": ("cddb query %(disc_id)s %(track_count)d " +
                                   "%(offsets)s %(seconds)d") %
                           {"disc_id": disc_id,
                            "track_count": disc_id.track_count,
                            "offsets": " ".join(map(str, disc_id.offsets)),
                            "seconds": disc_id.total_length}}))

    response = RESPONSE.match(m.readline())
    if (response is None):
        raise ValueError("invalid response from server")
    else:
        # a list of (category, disc id, disc title) tuples
        matches = []
        code = int(response.group(1))
        if (code == 200):
            # single exact match
            match = QUERY_RESULT.match(response.group(2))
            if (match is not None):
                matches.append((match.group(1),
                                match.group(2),
                                match.group(3)))
            else:
                raise ValueError("invalid query result")
        elif ((code == 211) or (code == 210)):
            # multiple exact or inexact matches
            line = m.readline()
            while (not line.startswith(".")):
                match = QUERY_RESULT.match(line)
                if (match is not None):
                    matches.append((match.group(1),
                                    match.group(2),
                                    match.group(3)))
                else:
                    raise ValueError("invalid query result")
                line = m.readline()
        elif (code == 202):
            # no match found
            pass
        else:
            # some error has occurred
            raise ValueError(response.group(2))

    m.close()

    if (len(matches) > 0):
        # for each result, query FreeDB for XMCD file data
        for (category, disc_id, title) in matches:
            from audiotools import VERSION

            sleep(1)  # add a slight delay to keep the server happy
            m = urlopen("http://%s:%d/~cddb/cddb.cgi" % (freedb_server,
                                                         freedb_port),
                        urlencode({"hello": "user %s %s %s" %
                                   (getfqdn(),
                                    "audiotools",
                                    VERSION),
                                   "proto": str(6),
                                   "cmd": ("cddb read %(category)s " +
                                           "%(disc_id)s") %
                                   {"category": category,
                                    "disc_id": disc_id}}))
            response = RESPONSE.match(m.readline())
            if (response is None):
                raise ValueError("invalid response from server")
            else:
                # FIXME - check response code here
                freedb = {}
                line = m.readline()
                while (not line.startswith(".")):
                    if (not line.startswith("#")):
                        entry = FREEDB_LINE.match(line)
                        if (entry is not None):
                            if (entry.group(1) in freedb):
                                freedb[entry.group(1)] += entry.group(2)
                            else:
                                freedb[entry.group(1)] = entry.group(2)
                    line = m.readline()
                yield list(xmcd_metadata(freedb))


def xmcd_metadata(freedb_file):
    """given a dict of KEY->value unicode strings,
    yields a MetaData object per track"""

    import re

    TTITLE = re.compile(r'TTITLE(\d+)')

    dtitle = freedb_file.get("DTITLE", "")
    if (" / " in dtitle):
        (album_artist, album_name) = dtitle.split(" / ", 1)
    else:
        album_artist = None
        album_name = dtitle

    year = freedb_file.get("DYEAR", None)

    ttitles = [(int(m.group(1)), value) for (m, value) in
               [(TTITLE.match(key), value) for (key, value) in
                freedb_file.items()] if m is not None]

    if (len(ttitles) > 0):
        track_total = max([tracknum for (tracknum, ttitle) in ttitles]) + 1
    else:
        track_total = 0

    for (tracknum, ttitle) in sorted(ttitles, key=lambda t: t[0]):
        if (" / " in ttitle):
            (track_artist,
             track_name) = ttitle.split(" / ", 1)
        else:
            track_artist = album_artist
            track_name = ttitle

        from audiotools import MetaData

        yield MetaData(
            track_name=track_name.decode('utf-8', 'replace'),
            track_number=tracknum + 1,
            track_total=track_total,
            album_name=album_name.decode('utf-8', 'replace'),
            artist_name=(track_artist.decode('utf-8', 'replace')
                         if track_artist is not None else None),
            year=(year.decode('utf-8', 'replace') if
                  year is not None else None))
