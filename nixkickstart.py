#
# kickstart.py: kickstart install support
#
# Copyright (C) 1999, 2000, 2001, 2002, 2003, 2004, 2005, 2006, 2007
# Red Hat, Inc.  All rights reserved.
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
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
# This is copied over and modified from pyanaconda/kickstart.py in order to
# avoid the full dependency on Anaconda and to allow only partitioning and
# filesystem creation commands.

from blivet.deviceaction import *
from blivet.devices import LUKSDevice
from blivet.devicelibs.lvm import getPossiblePhysicalExtents
from blivet.devicelibs import swap
from blivet.formats import getFormat
from blivet.partitioning import doPartitioning
from blivet.partitioning import growLVM
from blivet import udev
import blivet.arch
import blivet.platform
import blivet

import glob
import os
import os.path
import sys
import pykickstart.commands as commands

from pykickstart.base import KickstartCommand
from pykickstart.constants import *
from pykickstart.errors import formatErrorMsg, KickstartValueError
from pykickstart.parser import KickstartParser
from pykickstart.sections import *
from pykickstart.version import DEVEL, returnClassForVersion
from pykickstart.handlers.control import commandMap, dataMap

import logging
log = logging.getLogger("anaconda")
storage_log = logging.getLogger("blivet")

__all__ = ['NixKickstart']

def getEscrowCertificate(escrowCerts, url):
    if not url:
        return None

    if url in escrowCerts:
        return escrowCerts[url]

def deviceMatches(spec):
    full_spec = spec
    if not full_spec.startswith("/dev/"):
        full_spec = os.path.normpath("/dev/" + full_spec)

    # the regular case
    matches = udev.udev_resolve_glob(full_spec)
    dev = udev.udev_resolve_devspec(full_spec)
    # udev_resolve_devspec returns None if there's no match, but we don't
    # want that ending up in the list.
    if dev and dev not in matches:
        matches.append(dev)

    return matches

def lookupAlias(devicetree, alias):
    for dev in devicetree.devices:
        if getattr(dev, "req_name", None) == alias:
            return dev

    return None

# Remove any existing formatting on a device, but do not remove the partition
# itself.  This sets up an existing device to be used in a --onpart option.
def removeExistingFormat(device, storage):
    deps = storage.deviceDeps(device)
    while deps:
        leaves = [d for d in deps if d.isleaf]
        for leaf in leaves:
            storage.destroyDevice(leaf)
            deps.remove(leaf)

    storage.devicetree.registerAction(ActionDestroyFormat(device))

###
### SUBCLASSES OF PYKICKSTART COMMAND HANDLERS
###

class AutoPart(commands.autopart.F18_AutoPart):
    def execute(self, storage, ksdata):
        from blivet.partitioning import doAutoPartition

        if not self.autopart:
            return

        # sets up default autopartitioning.  use clearpart separately
        # if you want it
        blivet.platform.getPlatform().setDefaultPartitioning(storage)
        storage.doAutoPart = True

        if self.encrypted:
            storage.encryptedAutoPart = True
            storage.encryptionPassphrase = self.passphrase
            storage.encryptionCipher = self.cipher
            storage.autoPartEscrowCert = getEscrowCertificate(storage.escrowCertificates, self.escrowcert)
            storage.autoPartAddBackupPassphrase = self.backuppassphrase

        if self.type is not None:
            storage.autoPartType = self.type

        doAutoPartition(storage, ksdata)

class BTRFS(commands.btrfs.F17_BTRFS):
    def execute(self, storage, ksdata):
        for b in self.btrfsList:
            b.execute(storage, ksdata)

class BTRFSData(commands.btrfs.F17_BTRFSData):
    def execute(self, storage, ksdata):
        devicetree = storage.devicetree

        storage.doAutoPart = False

        members = []

        # Get a list of all the devices that make up this volume.
        for member in self.devices:
            # if using --onpart, use original device
            member_name = ksdata.onPart.get(member, member)
            if member_name:
                dev = devicetree.getDeviceByName(member_name) or lookupAlias(devicetree, member)
            if not dev:
                dev = devicetree.resolveDevice(member)

            if dev and dev.format.type == "luks":
                try:
                    dev = devicetree.getChildren(dev)[0]
                except IndexError:
                    dev = None
            if not dev:
                raise KickstartValueError, formatErrorMsg(self.lineno, msg="Tried to use undefined partition %s in BTRFS volume specification" % member)

            members.append(dev)

        if self.subvol:
            name = self.name
        elif self.label:
            name = self.label
        else:
            name = None

        if len(members) == 0 and not self.preexist:
            raise KickstartValueError, formatErrorMsg(self.lineno, msg="BTRFS volume defined without any member devices.  Either specify member devices or use --useexisting.")

        # allow creating btrfs vols/subvols without specifying mountpoint
        if self.mountpoint in ("none", "None"):
            self.mountpoint = ""

        # Sanity check mountpoint
        if self.mountpoint != "" and self.mountpoint[0] != '/':
            raise KickstartValueError, formatErrorMsg(self.lineno, msg="The mount point \"%s\" is not valid." % (self.mountpoint,))

        if self.preexist:
            device = devicetree.getDeviceByName(self.name)
            if not device:
                device = udev.udev_resolve_devspec(self.name)

            if not device:
                raise KickstartValueError, formatErrorMsg(self.lineno, msg="Specified nonexistent BTRFS volume %s in btrfs command" % self.name)
        else:
            # If a previous device has claimed this mount point, delete the
            # old one.
            try:
                if self.mountpoint:
                    device = storage.mountpoints[self.mountpoint]
                    storage.destroyDevice(device)
            except KeyError:
                pass

            request = storage.newBTRFS(name=name,
                                       subvol=self.subvol,
                                       mountpoint=self.mountpoint,
                                       metaDataLevel=self.metaDataLevel,
                                       dataLevel=self.dataLevel,
                                       parents=members)

            storage.createDevice(request)


class ClearPart(commands.clearpart.F17_ClearPart):
    def parse(self, args):
        retval = commands.clearpart.F17_ClearPart.parse(self, args)

        if self.type is None:
            self.type = CLEARPART_TYPE_NONE

        # Do any glob expansion now, since we need to have the real list of
        # disks available before the execute methods run.
        drives = []
        for spec in self.drives:
            matched = deviceMatches(spec)
            if matched:
                drives.extend(matched)
            else:
                raise KickstartValueError, formatErrorMsg(self.lineno, msg="Specified nonexistent disk %s in clearpart command" % spec)

        self.drives = drives

        # Do any glob expansion now, since we need to have the real list of
        # devices available before the execute methods run.
        devices = []
        for spec in self.devices:
            matched = deviceMatches(spec)
            if matched:
                devices.extend(matched)
            else:
                raise KickstartValueError, formatErrorMsg(self.lineno, msg="Specified nonexistent device %s in clearpart device list" % spec)

        self.devices = devices

        return retval

    def execute(self, storage, ksdata):
        storage.config.clearPartType = self.type
        storage.config.clearPartDisks = self.drives
        storage.config.clearPartDevices = self.devices

        if self.initAll:
            storage.config.initializeDisks = self.initAll

        storage.clearPartitions()

class IgnoreDisk(commands.ignoredisk.RHEL6_IgnoreDisk):
    def parse(self, args):
        retval = commands.ignoredisk.RHEL6_IgnoreDisk.parse(self, args)

        # See comment in ClearPart.parse
        drives = []
        for spec in self.ignoredisk:
            matched = deviceMatches(spec)
            if matched:
                drives.extend(matched)
            else:
                raise KickstartValueError, formatErrorMsg(self.lineno, msg="Specified nonexistent disk %s in ignoredisk command" % spec)

        self.ignoredisk = drives

        drives = []
        for spec in self.onlyuse:
            matched = deviceMatches(spec)
            if matched:
                drives.extend(matched)
            else:
                raise KickstartValueError, formatErrorMsg(self.lineno, msg="Specified nonexistent disk %s in ignoredisk command" % spec)

        self.onlyuse = drives

        return retval

class LogVol(commands.logvol.F18_LogVol):
    def execute(self, storage, ksdata):
        for l in self.lvList:
            l.execute(storage, ksdata)

        if self.lvList:
            growLVM(storage)

class LogVolData(commands.logvol.F18_LogVolData):
    def execute(self, storage, ksdata):
        devicetree = storage.devicetree

        storage.doAutoPart = False

        # we might have truncated or otherwise changed the specified vg name
        vgname = ksdata.onPart.get(self.vgname, self.vgname)

        if self.mountpoint == "swap":
            type = "swap"
            self.mountpoint = ""
            if self.recommended or self.hibernation:
                self.size = swap.swapSuggestion(hibernation=self.hibernation)
                self.grow = False
        else:
            if self.fstype != "":
                type = self.fstype
            else:
                type = storage.defaultFSType

        # Sanity check mountpoint
        if self.mountpoint != "" and self.mountpoint[0] != '/':
            raise KickstartValueError, formatErrorMsg(self.lineno, msg="The mount point \"%s\" is not valid." % (self.mountpoint,))

        # Check that the VG this LV is a member of has already been specified.
        vg = devicetree.getDeviceByName(vgname)
        if not vg:
            raise KickstartValueError, formatErrorMsg(self.lineno, msg="No volume group exists with the name \"%s\".  Specify volume groups before logical volumes." % self.vgname)

        # If this specifies an existing request that we should not format,
        # quit here after setting up enough information to mount it later.
        if not self.format:
            if not self.name:
                raise KickstartValueError, formatErrorMsg(self.lineno, msg="--noformat used without --name")

            dev = devicetree.getDeviceByName("%s-%s" % (vg.name, self.name))
            if not dev:
                raise KickstartValueError, formatErrorMsg(self.lineno, msg="No preexisting logical volume with the name \"%s\" was found." % self.name)

            if self.resize:
                if self.size < dev.currentSize:
                    # shrink
                    try:
                        devicetree.registerAction(ActionResizeFormat(dev, self.size))
                        devicetree.registerAction(ActionResizeDevice(dev, self.size))
                    except ValueError:
                        raise KickstartValueError(formatErrorMsg(self.lineno,
                                msg="Invalid target size (%d) for device %s" % (self.size, dev.name)))
                else:
                    # grow
                    try:
                        devicetree.registerAction(ActionResizeDevice(dev, self.size))
                        devicetree.registerAction(ActionResizeFormat(dev, self.size))
                    except ValueError:
                        raise KickstartValueError(formatErrorMsg(self.lineno,
                                msg="Invalid target size (%d) for device %s" % (self.size, dev.name)))

            dev.format.mountpoint = self.mountpoint
            dev.format.mountopts = self.fsopts
            return

        # Make sure this LV name is not already used in the requested VG.
        if not self.preexist:
            tmp = devicetree.getDeviceByName("%s-%s" % (vg.name, self.name))
            if tmp:
                raise KickstartValueError, formatErrorMsg(self.lineno, msg="Logical volume name already used in volume group %s" % vg.name)

            # Size specification checks
            if not self.percent:
                if not self.size:
                    raise KickstartValueError, formatErrorMsg(self.lineno, msg="Size required")
                elif not self.grow and self.size*1024 < vg.peSize:
                    raise KickstartValueError, formatErrorMsg(self.lineno, msg="Logical volume size must be larger than the volume group physical extent size.")
            elif self.percent <= 0 or self.percent > 100:
                raise KickstartValueError, formatErrorMsg(self.lineno, msg="Percentage must be between 0 and 100")

        # Now get a format to hold a lot of these extra values.
        format = getFormat(type,
                           mountpoint=self.mountpoint,
                           label=self.label,
                           fsprofile=self.fsprofile,
                           mountopts=self.fsopts)
        if not format.type:
            raise KickstartValueError, formatErrorMsg(self.lineno, msg="The \"%s\" filesystem type is not supported." % type)

        # If we were given a pre-existing LV to create a filesystem on, we need
        # to verify it and its VG exists and then schedule a new format action
        # to take place there.  Also, we only support a subset of all the
        # options on pre-existing LVs.
        if self.preexist:
            device = devicetree.getDeviceByName("%s-%s" % (vg.name, self.name))
            if not device:
                raise KickstartValueError, formatErrorMsg(self.lineno, msg="Specified nonexistent LV %s in logvol command" % self.name)

            removeExistingFormat(device, storage)

            if self.resize:
                try:
                    devicetree.registerAction(ActionResizeDevice(device, self.size))
                except ValueError:
                    raise KickstartValueError(formatErrorMsg(self.lineno,
                            msg="Invalid target size (%d) for device %s" % (self.size, device.name)))

            devicetree.registerAction(ActionCreateFormat(device, format))
        else:
            # If a previous device has claimed this mount point, delete the
            # old one.
            try:
                if self.mountpoint:
                    device = storage.mountpoints[self.mountpoint]
                    storage.destroyDevice(device)
            except KeyError:
                pass

            request = storage.newLV(format=format,
                                    name=self.name,
                                    parents=[vg],
                                    size=self.size,
                                    grow=self.grow,
                                    maxsize=self.maxSizeMB,
                                    percent=self.percent)

            storage.createDevice(request)

        if self.encrypted:
            if self.passphrase and not storage.encryptionPassphrase:
                storage.encryptionPassphrase = self.passphrase

            cert = getEscrowCertificate(storage.escrowCertificates, self.escrowcert)
            if self.preexist:
                luksformat = format
                device.format = getFormat("luks", passphrase=self.passphrase, device=device.path,
                                          cipher=self.cipher,
                                          escrow_cert=cert,
                                          add_backup_passphrase=self.backuppassphrase)
                luksdev = LUKSDevice("luks%d" % storage.nextID,
                                     format=luksformat,
                                     parents=device)
            else:
                luksformat = request.format
                request.format = getFormat("luks", passphrase=self.passphrase,
                                           cipher=self.cipher,
                                           escrow_cert=cert,
                                           add_backup_passphrase=self.backuppassphrase)
                luksdev = LUKSDevice("luks%d" % storage.nextID,
                                     format=luksformat,
                                     parents=request)
            storage.createDevice(luksdev)

class Logging(commands.logging.FC6_Logging):
    def execute(self, *args):
        if logger.tty_loglevel == DEFAULT_TTY_LEVEL:
            # not set from the command line
            level = logLevelMap[self.level]
            logger.tty_loglevel = level
            setHandlersLevel(log, level)
            setHandlersLevel(storage_log, level)

        if logger.remote_syslog == None and len(self.host) > 0:
            # not set from the command line, ok to use kickstart
            remote_server = self.host
            if self.port:
                remote_server = "%s:%s" %(self.host, self.port)
            logger.updateRemote(remote_server)

class Partition(commands.partition.F18_Partition):
    def execute(self, storage, ksdata):
        for p in self.partitions:
            p.execute(storage, ksdata)

        if self.partitions:
            doPartitioning(storage)

class PartitionData(commands.partition.F18_PartData):
    def execute(self, storage, ksdata):
        devicetree = storage.devicetree
        kwargs = {}

        storage.doAutoPart = False

        if self.onbiosdisk != "":
            for (disk, biosdisk) in storage.eddDict.iteritems():
                if "%x" % biosdisk == self.onbiosdisk:
                    self.disk = disk
                    break

            if not self.disk:
                raise KickstartValueError, formatErrorMsg(self.lineno, msg="Specified BIOS disk %s cannot be determined" % self.onbiosdisk)

        if self.mountpoint == "swap":
            type = "swap"
            self.mountpoint = ""
            if self.recommended or self.hibernation:
                self.size = swap.swapSuggestion(hibernation=self.hibernation)
                self.grow = False
        # if people want to specify no mountpoint for some reason, let them
        # this is really needed for pSeries boot partitions :(
        elif self.mountpoint == "None":
            self.mountpoint = ""
            if self.fstype:
                type = self.fstype
            else:
                type = storage.defaultFSType
        elif self.mountpoint == 'appleboot':
            type = "appleboot"
            self.mountpoint = ""
        elif self.mountpoint == 'prepboot':
            type = "prepboot"
            self.mountpoint = ""
        elif self.mountpoint == 'biosboot':
            type = "biosboot"
            self.mountpoint = ""
        elif self.mountpoint.startswith("raid."):
            type = "mdmember"
            kwargs["name"] = self.mountpoint
            self.mountpoint = ""

            if devicetree.getDeviceByName(kwargs["name"]):
                raise KickstartValueError, formatErrorMsg(self.lineno, msg="RAID partition defined multiple times")

            if self.onPart:
                ksdata.onPart[kwargs["name"]] = self.onPart
        elif self.mountpoint.startswith("pv."):
            type = "lvmpv"
            kwargs["name"] = self.mountpoint
            self.mountpoint = ""

            if devicetree.getDeviceByName(kwargs["name"]):
                raise KickstartValueError, formatErrorMsg(self.lineno, msg="PV partition defined multiple times")

            if self.onPart:
                ksdata.onPart[kwargs["name"]] = self.onPart
        elif self.mountpoint.startswith("btrfs."):
            type = "btrfs"
            kwargs["name"] = self.mountpoint
            self.mountpoint = ""

            if devicetree.getDeviceByName(kwargs["name"]):
                raise KickstartValueError, formatErrorMsg(self.lineno, msg="BTRFS partition defined multiple times")

            if self.onPart:
                ksdata.onPart[kwargs["name"]] = self.onPart
        elif self.mountpoint == "/boot/efi":
            if blivet.arch.isMactel():
                type = "hfs+"
            else:
                type = "EFI System Partition"
                self.fsopts = "defaults,uid=0,gid=0,umask=0077,shortname=winnt"
        else:
            if self.fstype != "":
                type = self.fstype
            elif self.mountpoint == "/boot":
                type = storage.defaultBootFSType
            else:
                type = storage.defaultFSType

        # If this specified an existing request that we should not format,
        # quit here after setting up enough information to mount it later.
        if not self.format:
            if not self.onPart:
                raise KickstartValueError, formatErrorMsg(self.lineno, msg="--noformat used without --onpart")

            dev = devicetree.getDeviceByName(udev.udev_resolve_devspec(self.onPart))
            if not dev:
                raise KickstartValueError, formatErrorMsg(self.lineno, msg="No preexisting partition with the name \"%s\" was found." % self.onPart)

            if self.resize:
                if self.size < dev.currentSize:
                    # shrink
                    try:
                        devicetree.registerAction(ActionResizeFormat(dev, self.size))
                        devicetree.registerAction(ActionResizeDevice(dev, self.size))
                    except ValueError:
                        raise KickstartValueError(formatErrorMsg(self.lineno,
                                msg="Invalid target size (%d) for device %s" % (self.size, dev.name)))
                else:
                    # grow
                    try:
                        devicetree.registerAction(ActionResizeDevice(dev, self.size))
                        devicetree.registerAction(ActionResizeFormat(dev, self.size))
                    except ValueError:
                        raise KickstartValueError(formatErrorMsg(self.lineno,
                                msg="Invalid target size (%d) for device %s" % (self.size, dev.name)))

            dev.format.mountpoint = self.mountpoint
            dev.format.mountopts = self.fsopts
            return

        # Now get a format to hold a lot of these extra values.
        kwargs["format"] = getFormat(type,
                                     mountpoint=self.mountpoint,
                                     label=self.label,
                                     fsprofile=self.fsprofile,
                                     mountopts=self.fsopts)
        if not kwargs["format"].type:
            raise KickstartValueError, formatErrorMsg(self.lineno, msg="The \"%s\" filesystem type is not supported." % type)

        # If we were given a specific disk to create the partition on, verify
        # that it exists first.  If it doesn't exist, see if it exists with
        # mapper/ on the front.  If that doesn't exist either, it's an error.
        if self.disk:
            names = [self.disk, "mapper/" + self.disk]
            for n in names:
                disk = devicetree.getDeviceByName(udev.udev_resolve_devspec(n))
                # if this is a multipath member promote it to the real mpath
                if disk and disk.format.type == "multipath_member":
                    mpath_device = storage.devicetree.getChildren(disk)[0]
                    storage_log.info("kickstart: part: promoting %s to %s"
                                     % (disk.name, mpath_device.name))
                    disk = mpath_device
                if not disk:
                    raise KickstartValueError, formatErrorMsg(self.lineno, msg="Specified nonexistent disk %s in partition command" % n)
                if not disk.partitionable:
                    raise KickstartValueError, formatErrorMsg(self.lineno, msg="Cannot install to read-only media %s." % n)

                should_clear = storage.shouldClear(disk)
                if disk and (disk.partitioned or should_clear):
                    kwargs["parents"] = [disk]
                    break
                elif disk:
                    raise KickstartValueError, formatErrorMsg(self.lineno, msg="Specified unpartitioned disk %s in partition command" % self.disk)

            if not kwargs["parents"]:
                raise KickstartValueError, formatErrorMsg(self.lineno, msg="Specified nonexistent disk %s in partition command" % self.disk)

        kwargs["grow"] = self.grow
        kwargs["size"] = self.size
        kwargs["maxsize"] = self.maxSizeMB
        kwargs["primary"] = self.primOnly

        # If we were given a pre-existing partition to create a filesystem on,
        # we need to verify it exists and then schedule a new format action to
        # take place there.  Also, we only support a subset of all the options
        # on pre-existing partitions.
        if self.onPart:
            device = devicetree.getDeviceByName(udev.udev_resolve_devspec(self.onPart))
            if not device:
                raise KickstartValueError, formatErrorMsg(self.lineno, msg="Specified nonexistent partition %s in partition command" % self.onPart)

            removeExistingFormat(device, storage)
            if self.resize:
                try:
                    devicetree.registerAction(ActionResizeDevice(device, self.size))
                except ValueError:
                    raise KickstartValueError(formatErrorMsg(self.lineno,
                            msg="Invalid target size (%d) for device %s" % (self.size, device.name)))

            devicetree.registerAction(ActionCreateFormat(device, kwargs["format"]))
        else:
            # If a previous device has claimed this mount point, delete the
            # old one.
            try:
                if self.mountpoint:
                    device = storage.mountpoints[self.mountpoint]
                    storage.destroyDevice(device)
            except KeyError:
                pass

            request = storage.newPartition(**kwargs)
            storage.createDevice(request)

        if self.encrypted:
            if self.passphrase and not storage.encryptionPassphrase:
               storage.encryptionPassphrase = self.passphrase

            cert = getEscrowCertificate(storage.escrowCertificates, self.escrowcert)
            if self.onPart:
                luksformat = format
                device.format = getFormat("luks", passphrase=self.passphrase, device=device.path,
                                          cipher=self.cipher,
                                          escrow_cert=cert,
                                          add_backup_passphrase=self.backuppassphrase)
                luksdev = LUKSDevice("luks%d" % storage.nextID,
                                     format=luksformat,
                                     parents=device)
            else:
                luksformat = request.format
                request.format = getFormat("luks", passphrase=self.passphrase,
                                           cipher=self.cipher,
                                           escrow_cert=cert,
                                           add_backup_passphrase=self.backuppassphrase)
                luksdev = LUKSDevice("luks%d" % storage.nextID,
                                     format=luksformat,
                                     parents=request)
            storage.createDevice(luksdev)

class Raid(commands.raid.F19_Raid):
    def execute(self, storage, ksdata):
        for r in self.raidList:
            r.execute(storage, ksdata)

class RaidData(commands.raid.F18_RaidData):
    def execute(self, storage, ksdata):
        raidmems = []
        devicetree = storage.devicetree
        devicename = self.device
        if self.preexist:
            device = devicetree.resolveDevice(devicename)
            if device:
                devicename = device.name

        kwargs = {}

        storage.doAutoPart = False

        if self.mountpoint == "swap":
            type = "swap"
            self.mountpoint = ""
        elif self.mountpoint.startswith("pv."):
            type = "lvmpv"
            kwargs["name"] = self.mountpoint
            ksdata.onPart[kwargs["name"]] = devicename

            if devicetree.getDeviceByName(kwargs["name"]):
                raise KickstartValueError, formatErrorMsg(self.lineno, msg="PV partition defined multiple times")

            self.mountpoint = ""
        elif self.mountpoint.startswith("btrfs."):
            type = "btrfs"
            kwargs["name"] = self.mountpoint
            ksdata.onPart[kwargs["name"]] = devicename

            if devicetree.getDeviceByName(kwargs["name"]):
                raise KickstartValueError, formatErrorMsg(self.lineno, msg="BTRFS partition defined multiple times")

            self.mountpoint = ""
        else:
            if self.fstype != "":
                type = self.fstype
            elif self.mountpoint == "/boot" and \
                 "mdarray" in storage.bootloader.stage2_device_types:
                type = storage.defaultBootFSType
            else:
                type = storage.defaultFSType

        # Sanity check mountpoint
        if self.mountpoint != "" and self.mountpoint[0] != '/':
            raise KickstartValueError, formatErrorMsg(self.lineno, msg="The mount point is not valid.")

        # If this specifies an existing request that we should not format,
        # quit here after setting up enough information to mount it later.
        if not self.format:
            if not devicename:
                raise KickstartValueError, formatErrorMsg(self.lineno, msg="--noformat used without --device")

            dev = devicetree.getDeviceByName(devicename)
            if not dev:
                raise KickstartValueError, formatErrorMsg(self.lineno, msg="No preexisting RAID device with the name \"%s\" was found." % devicename)

            dev.format.mountpoint = self.mountpoint
            dev.format.mountopts = self.fsopts
            return

        # Get a list of all the RAID members.
        for member in self.members:
            # if member is using --onpart, use original device
            mem = ksdata.onPart.get(member, member)
            dev = devicetree.getDeviceByName(mem) or lookupAlias(devicetree, mem)
            if dev and dev.format.type == "luks":
                try:
                    dev = devicetree.getChildren(dev)[0]
                except IndexError:
                    dev = None
            if not dev:
                raise KickstartValueError, formatErrorMsg(self.lineno, msg="Tried to use undefined partition %s in RAID specification" % mem)

            raidmems.append(dev)

        # Now get a format to hold a lot of these extra values.
        kwargs["format"] = getFormat(type,
                                     label=self.label,
                                     fsprofile=self.fsprofile,
                                     mountpoint=self.mountpoint,
                                     mountopts=self.fsopts)
        if not kwargs["format"].type:
            raise KickstartValueError, formatErrorMsg(self.lineno, msg="The \"%s\" filesystem type is not supported." % type)

        kwargs["name"] = devicename
        kwargs["level"] = self.level
        kwargs["parents"] = raidmems
        kwargs["memberDevices"] = len(raidmems) - self.spares
        kwargs["totalDevices"] = len(raidmems)

        # If we were given a pre-existing RAID to create a filesystem on,
        # we need to verify it exists and then schedule a new format action
        # to take place there.  Also, we only support a subset of all the
        # options on pre-existing RAIDs.
        if self.preexist:
            device = devicetree.getDeviceByName(devicename)
            if not device:
                raise KickstartValueError, formatErrorMsg(self.lineno, msg="Specifeid nonexistent RAID %s in raid command" % devicename)

            removeExistingFormat(device, storage)
            devicetree.registerAction(ActionCreateFormat(device, kwargs["format"]))
        else:
            if devicename and devicename in (a.name for a in storage.mdarrays):
                raise KickstartValueError(formatErrorMsg(self.lineno, msg="The Software RAID array name \"%s\" is already in use." % devicename))

            # If a previous device has claimed this mount point, delete the
            # old one.
            try:
                if self.mountpoint:
                    device = storage.mountpoints[self.mountpoint]
                    storage.destroyDevice(device)
            except KeyError:
                pass

            try:
                request = storage.newMDArray(**kwargs)
            except ValueError as e:
                raise KickstartValueError, formatErrorMsg(self.lineno, msg=str(e))

            storage.createDevice(request)

        if self.encrypted:
            if self.passphrase and not storage.encryptionPassphrase:
               storage.encryptionPassphrase = self.passphrase

            cert = getEscrowCertificate(storage.escrowCertificates, self.escrowcert)
            if self.preexist:
                luksformat = format
                device.format = getFormat("luks", passphrase=self.passphrase, device=device.path,
                                          cipher=self.cipher,
                                          escrow_cert=cert,
                                          add_backup_passphrase=self.backuppassphrase)
                luksdev = LUKSDevice("luks%d" % storage.nextID,
                                     format=luksformat,
                                     parents=device)
            else:
                luksformat = request.format
                request.format = getFormat("luks", passphrase=self.passphrase,
                                           cipher=self.cipher,
                                           escrow_cert=cert,
                                           add_backup_passphrase=self.backuppassphrase)
                luksdev = LUKSDevice("luks%d" % storage.nextID,
                                     format=luksformat,
                                     parents=request)
            storage.createDevice(luksdev)

class VolGroup(commands.volgroup.FC16_VolGroup):
    def execute(self, storage, ksdata):
        for v in self.vgList:
            v.execute(storage, ksdata)

class VolGroupData(commands.volgroup.FC16_VolGroupData):
    def execute(self, storage, ksdata):
        pvs = []

        devicetree = storage.devicetree

        storage.doAutoPart = False

        # Get a list of all the physical volume devices that make up this VG.
        for pv in self.physvols:
            # if pv is using --onpart, use original device
            pv = ksdata.onPart.get(pv, pv)
            dev = devicetree.getDeviceByName(pv) or lookupAlias(devicetree, pv)
            if dev and dev.format.type == "luks":
                try:
                    dev = devicetree.getChildren(dev)[0]
                except IndexError:
                    dev = None
            if not dev:
                raise KickstartValueError, formatErrorMsg(self.lineno, msg="Tried to use undefined partition %s in Volume Group specification" % pv)

            pvs.append(dev)

        if len(pvs) == 0 and not self.preexist:
            raise KickstartValueError, formatErrorMsg(self.lineno, msg="Volume group defined without any physical volumes.  Either specify physical volumes or use --useexisting.")

        if self.pesize not in getPossiblePhysicalExtents(floor=1024):
            raise KickstartValueError, formatErrorMsg(self.lineno, msg="Volume group specified invalid pesize")

        # If --noformat or --useexisting was given, there's really nothing to do.
        if not self.format or self.preexist:
            if not self.vgname:
                raise KickstartValueError, formatErrorMsg(self.lineno, msg="--noformat or --useexisting used without giving a name")

            dev = devicetree.getDeviceByName(self.vgname)
            if not dev:
                raise KickstartValueError, formatErrorMsg(self.lineno, msg="No preexisting VG with the name \"%s\" was found." % self.vgname)
        elif self.vgname in (vg.name for vg in storage.vgs):
            raise KickstartValueError(formatErrorMsg(self.lineno, msg="The volume group name \"%s\" is already in use." % self.vgname))
        else:
            request = storage.newVG(parents=pvs,
                                    name=self.vgname,
                                    peSize=self.pesize/1024.0)

            storage.createDevice(request)
            if self.reserved_space:
                request.reserved_space = self.reserved_space
            elif self.reserved_percent:
                request.reserved_percent = self.reserved_percent

            # in case we had to truncate or otherwise adjust the specified name
            ksdata.onPart[self.vgname] = request.name


# This is just the latest entry from pykickstart.handlers.control with all the
# classes we're overriding in place of the defaults.

def get_kshandler():
    default_cmds = commandMap[DEVEL]
    default_data = dataMap[DEVEL]

    nixos_cmd_map = {
        "autopart": AutoPart,
        "btrfs": BTRFS,
        "clearpart": ClearPart,
        "device": default_cmds.get("device"),
        "deviceprobe": default_cmds.get("deviceprobe"),
        "harddrive": default_cmds.get("harddrive"),
        "ignoredisk": IgnoreDisk,
        "logvol": LogVol,
        "part": Partition,
        "partition": Partition,
        "raid": Raid,
        "volgroup": VolGroup,
        "zerombr": default_cmds.get("zerombr"),
    }

    nixos_data_map = {
        "BTRFSData": BTRFSData,
        "DeviceData": default_data.get("DeviceData"),
        "LogVolData": LogVolData,
        "PartData": PartitionData,
        "RaidData": RaidData,
        "VolGroupData": VolGroupData,
    }

    cls = returnClassForVersion()
    return cls(mapping=nixos_cmd_map, dataMapping=nixos_data_map)

class MonkeyBootLoader(object):
    """
    Heavy monkey-patching, we don't want blivet to do anything regarding the
    bootloader, because on NixOS this is done by the activation script.
    """
    skip_bootloader = True
    set_disk_list = lambda s, d: None

class NixKickstart(object):
    def __init__(self, ks_script):
        self.handler = get_kshandler()
        self.handler.onPart = {}

        # monkey patching
        ksparser = KickstartParser(self.handler, followIncludes=False)
        ksparser.readKickstartFromString(ks_script)
        blivet.flags.installer_mode = True
        blivet.get_bootloader = MonkeyBootLoader
        blivet.Blivet.bootDisk = property(lambda s: None)
        blivet.Blivet.dumpState = lambda s, d: None

        self.storage = blivet.Blivet(self.handler)

    def run(self):
        blivet.platform.reset_platform()

        self.storage.shutdown()
        self.storage.config.update(self.handler)
        self.storage.reset()

        self.handler.clearpart.execute(self.storage, self.handler)
        if not any(d for d in self.storage.disks
                   if not d.format.hidden and not d.protected):
            return self.storage
        self.handler.autopart.execute(self.storage, self.handler)
        self.handler.partition.execute(self.storage, self.handler)
        self.handler.raid.execute(self.storage, self.handler)
        self.handler.volgroup.execute(self.storage, self.handler)
        self.handler.logvol.execute(self.storage, self.handler)
        self.handler.btrfs.execute(self.storage, self.handler)
        self.storage.doIt()
        return self.storage
