"""
WARNING!!!!!

compressed는 반영 X
"""

import os
import struct
from dataclasses import dataclass
from shutil import copyfileobj

COOKIE = b"MEI\014\013\012\013\016"
# 구버전에서는 pylibname (64s)가 없음.
COOKIE_FORMAT = "!8sIIII64s"
COOKIE_LENGTH = struct.calcsize(COOKIE_FORMAT)

TOC_ENTRY_FORMAT = "!IIIIBc"
TOC_ENTRY_LENGTH = struct.calcsize(TOC_ENTRY_FORMAT)


@dataclass
class Entry:
    name: str
    typecode: str
    compressed: bool
    rawdata: bytes
    uncompressed_length: int


class Pack:
    def __init__(self, filename: str) -> None:
        self.f = open(filename, "rb")

        # TODO: 개선하기
        self.f.seek(0, os.SEEK_END)
        self.f.seek(-8192, os.SEEK_CUR)

        pos = self.f.tell()
        buf = self.f.read()

        f = buf.find(COOKIE)
        if f == -1:
            print("no cookie")
            os._exit(1)

        self.cookie_start = pos + f

        self.f.seek(self.cookie_start, os.SEEK_SET)

        magic, archive_length, toc_offset, toc_length, pyvers, pylib_name = (
            struct.unpack(COOKIE_FORMAT, self.f.read(COOKIE_LENGTH))
        )

        self.archive_start_offset = (self.cookie_start + COOKIE_LENGTH) - archive_length
        print(filename, self.archive_start_offset)

        self.pylib_name = pylib_name
        self.pyvers = pyvers

        # parse toc
        self.f.seek(self.archive_start_offset + toc_offset, os.SEEK_SET)
        toc_data = self.f.read(toc_length)

        self.entries = self._parse_toc(toc_data)

    def _parse_toc(self, data: bytes) -> dict[str, Entry]:
        entry = {}
        cur_pos = 0

        while cur_pos < len(data):
            (
                entry_length,
                data_offset,
                data_length,
                uncompressed_length,
                compression_flag,
                typecode,
            ) = struct.unpack(
                TOC_ENTRY_FORMAT, data[cur_pos : (cur_pos + TOC_ENTRY_LENGTH)]
            )
            
            cur_pos += TOC_ENTRY_LENGTH

            name_length = entry_length - TOC_ENTRY_LENGTH
            name = data[cur_pos : (cur_pos + name_length)]

            cur_pos += name_length
            name = name.rstrip(b"\0").decode("utf-8")

            typecode = typecode.decode("ascii")

            if name in entry:
                print("WARNING!! dup")

            self.f.seek(self.archive_start_offset + data_offset, os.SEEK_SET)
            entry[name] = Entry(
                name=name,
                rawdata=self.f.read(data_length),
                compressed=bool(compression_flag),
                typecode=typecode,
                uncompressed_length=uncompressed_length,
            )

        return entry

    def save(self, filename: str):
        with open(filename, "wb") as dst:
            # copy
            self.f.seek(0, os.SEEK_SET)
            copyfileobj(self.f, dst)

            dst.seek(self.archive_start_offset, os.SEEK_SET)

            toc = bytearray()

            before_write_archive = dst.tell()
            for entry in self.entries.values():
                data_offset = dst.tell() - self.archive_start_offset
                name = entry.name.encode() + b"\x00"

                entry_length = TOC_ENTRY_LENGTH + len(name)
                if entry_length % 16 != 0:
                    padding_length = 16 - (entry_length % 16)
                    name += b"\x00" * padding_length

                    entry_length += padding_length

                toc.extend(
                    struct.pack(
                        TOC_ENTRY_FORMAT,
                        entry_length,
                        data_offset,
                        len(entry.rawdata),
                        entry.uncompressed_length,
                        int(entry.compressed),
                        entry.typecode.encode(),
                    )
                    + name
                )
                dst.write(entry.rawdata)

            toc_offset = dst.tell() - self.archive_start_offset
            dst.write(toc)
            archive_length = dst.tell() - before_write_archive + COOKIE_LENGTH

            dst.write(
                struct.pack(
                    COOKIE_FORMAT,
                    COOKIE,
                    archive_length,
                    toc_offset,
                    len(toc),
                    self.pyvers,
                    self.pylib_name,
                )
            )

            dst.truncate()

