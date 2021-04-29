# Copyright mio authors & contributors <https://github.com/mirukana/mio>
# SPDX-License-Identifier: LGPL-3.0-or-later

from dataclasses import dataclass

from ..core.errors import MioError


@dataclass
class QueriedDeviceError(MioError):
    pass


@dataclass
class DeviceUserIdMismatch(QueriedDeviceError):
    top_level_user_id: str
    info_user_id:      str


@dataclass
class DeviceIdMismatch(QueriedDeviceError):
    top_level_device_id: str
    info_device_id:      str


@dataclass
class DeviceEd25519Mismatch(QueriedDeviceError):
    saved_ed25519: str
    info_ed25519:  str
