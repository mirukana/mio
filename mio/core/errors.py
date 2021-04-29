# Copyright mio authors & contributors <https://github.com/mirukana/mio>
# SPDX-License-Identifier: LGPL-3.0-or-later

class MioError(Exception):
    def __str__(self) -> str:
        return repr(self)
