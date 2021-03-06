import re
import os
import logging
from autotest.client import utils
from autotest.client import lv_utils
from autotest.client.shared import error
from virttest import utils_libvirtd
from virttest import libvirt_storage
from virttest import utils_test
from virttest import virsh


def run(test, params, env):
    """
    Test the virsh pool commands

    (1) Define a given type pool
    (2) List pool with '--inactive --type' options
    (3) Dumpxml for the pool
    (4) Undefine the pool
    (5) Define pool by using the XML file in step (3)
    (6) Build the pool(except 'disk' type pool
        For 'fs' type pool, cover --overwrite and --no-overwrite options
    (7) Start the pool
    (8) List pool with '--persistent --type' options
    (9) Mark pool autostart
    (10) List pool with '--autostart --type' options
    (11) Restart libvirtd and list pool with '--autostart --persistent' options
    (12) Destroy the pool
    (13) Unmark pool autostart
    (14) Repeat step (11)
    (15) Start the pool
    (16) Get pool info
    (17) Get pool uuid by name
    (18) Get pool name by uuid
    (19) Refresh the pool
         For 'dir' type pool, touch a file under target path and refresh again
         to make the new file show in vol-list.
    (20) Destroy the pool
    (21) Delete pool for 'dir' type pool. After the command, the pool object
         will still exist but target path will be deleted
    (22) Undefine the pool
    """

    # Initialize the variables
    pool_name = params.get("pool_name", "temp_pool_1")
    pool_type = params.get("pool_type", "dir")
    pool_target = params.get("pool_target", "")
    # The file for dumped pool xml
    pool_xml = os.path.join(test.tmpdir, "pool.xml.tmp")
    if os.path.dirname(pool_target) is "":
        pool_target = os.path.join(test.tmpdir, pool_target)
    vol_name = params.get("vol_name", "temp_vol_1")
    # Use pool name as VG name
    vg_name = pool_name
    status_error = "yes" == params.get("status_error", "no")
    vol_path = os.path.join(pool_target, vol_name)
    # Clean up flags:
    # cleanup_env[0] for nfs, cleanup_env[1] for iscsi, cleanup_env[2] for lvm
    # cleanup_env[3] for selinux backup status.
    cleanup_env = [False, False, False, ""]

    def check_exit_status(result, expect_error=False):
        """
        Check the exit status of virsh commands.

        :param result: Virsh command result object
        :param expect_error: Boolean value, expect command success or fail
        """
        if not expect_error:
            if result.exit_status != 0:
                raise error.TestFail(result.stderr)
            else:
                logging.debug("Command output:\n%s", result.stdout.strip())
        elif expect_error and result.exit_status == 0:
            raise error.TestFail("Expect fail, but run successfully.")

    def check_pool_list(pool_name, option="--all", expect_error=False):
        """
        Check pool by running pool-list command with given option.

        :param pool_name: Name of the pool
        :param option: option for pool-list command
        :param expect_error: Boolean value, expect command success or fail
        """
        found = False
        # Get the list stored in a variable
        result = virsh.pool_list(option, ignore_status=True)
        check_exit_status(result, False)
        output = re.findall(r"(\S+)\ +(\S+)\ +(\S+)[\ +\n]",
                            str(result.stdout))
        for item in output:
            if pool_name in item[0]:
                found = True
                break
        if found:
            logging.debug("Find pool '%s' in pool list.", pool_name)
        else:
            logging.debug("Not find pool %s in pool list.", pool_name)
        if expect_error and found:
            raise error.TestFail("Unexpect pool '%s' exist." % pool_name)
        if not expect_error and not found:
            raise error.TestFail("Expect pool '%s' doesn't exist." % pool_name)

    def check_vol_list(vol_name, pool_name):
        """
        Check volume from the list

        :param vol_name: Name of the volume
        :param pool_name: Name of the pool
        """
        found = False
        # Get the volume list stored in a variable
        result = virsh.vol_list(pool_name, ignore_status=True)
        check_exit_status(result)

        output = re.findall(r"(\S+)\ +(\S+)[\ +\n]", str(result.stdout))
        for item in output:
            if vol_name in item[0]:
                found = True
                break
        if found:
            logging.debug(
                "Find volume '%s' in pool '%s'.", vol_name, pool_name)
        else:
            raise error.TestFail(
                "Not find volume '%s' in pool '%s'." %
                (vol_name, pool_name))

    def check_pool_info(pool_info, check_point, value):
        """
        Check the pool name, uuid, etc.

        :param pool_info: A dict include pool's information
        :param key: Key of pool info dict, available value: Name, UUID, State
                    Persistent, Autostart, Capacity, Allocation, Available
        :param value: Expect value of pool_info[key]
        """
        if pool_info is None:
            raise error.TestFail("Pool info dictionary is needed.")
        if pool_info[check_point] == value:
            logging.debug("Pool '%s' is '%s'.", check_point, value)
        else:
            raise error.TestFail("Pool '%s' isn't '%s'." % (check_point,
                                                            value))

    # Run Testcase
    try:
        _pool = libvirt_storage.StoragePool()
        # Step (1)
        # Pool define
        result = utils_test.libvirt.define_pool(pool_name, pool_type,
                                                pool_target, cleanup_env)
        check_exit_status(result, status_error)

        # Step (2)
        # Pool list
        option = "--inactive --type %s" % pool_type
        check_pool_list(pool_name, option)

        # Step (3)
        # Pool dumpxml
        xml = virsh.pool_dumpxml(pool_name, to_file=pool_xml)
        logging.debug("Pool '%s' XML:\n%s", pool_name, xml)

        # Step (4)
        # Undefine pool
        result = virsh.pool_undefine(pool_name, ignore_status=True)
        check_exit_status(result)
        check_pool_list(pool_name, "--all", True)

        # Step (5)
        # Define pool from XML file
        result = virsh.pool_define(pool_xml)
        check_exit_status(result, status_error)

        # Step (6)
        # Buid pool, this step may fail for 'disk' and 'logical' types pool
        if pool_type not in ["disk", "logical"]:
            option = ""
        # Options --overwrite and --no-overwrite can only be used to
        # build a filesystem pool, but it will fail for now
            # if pool_type == "fs":
            #    option = '--overwrite'
            result = virsh.pool_build(pool_name, option, ignore_status=True)
            check_exit_status(result)

        # Step (7)
        # Pool start
        result = virsh.pool_start(pool_name, ignore_status=True)
        check_exit_status(result)

        # Step (8)
        # Pool list
        option = "--persistent --type %s" % pool_type
        check_pool_list(pool_name, option)

        # Step (9)
        # Pool autostart
        result = virsh.pool_autostart(pool_name, ignore_status=True)
        check_exit_status(result)

        # Step (10)
        # Pool list
        option = "--autostart --type %s" % pool_type
        check_pool_list(pool_name, option)

        # Step (11)
        # Restart libvirtd and check the autostart pool
        utils_libvirtd.libvirtd_restart()
        option = "--autostart --persistent"
        check_pool_list(pool_name, option)

        # Step (12)
        # Pool destroy
        if virsh.pool_destroy(pool_name):
            logging.debug("Pool %s destroyed.", pool_name)
        else:
            raise error.TestFail("Destroy pool % failed." % pool_name)

        # Step (13)
        # Pool autostart disable
        result = virsh.pool_autostart(pool_name, "--disable",
                                      ignore_status=True)
        check_exit_status(result)

        # Step (14)
        # Repeat step (11)
        utils_libvirtd.libvirtd_restart()
        option = "--autostart"
        check_pool_list(pool_name, option, True)

        # Step (15)
        # Pool start
        # If the filesystem cntaining the directory is mounted, then the
        # directory will show as running, which means the local 'dir' pool
        # don't need start after restart libvirtd
        if pool_type != "dir":
            result = virsh.pool_start(pool_name, ignore_status=True)
            check_exit_status(result)

        # Step (16)
        # Pool info
        pool_info = _pool.pool_info(pool_name)
        logging.debug("Pool '%s' info:\n%s", pool_name, pool_info)

        # Step (17)
        # Pool UUID
        result = virsh.pool_uuid(pool_info["Name"], ignore_status=True)
        check_exit_status(result)
        check_pool_info(pool_info, "UUID", result.stdout.strip())

        # Step (18)
        # Pool Name
        result = virsh.pool_name(pool_info["UUID"], ignore_status=True)
        check_exit_status(result)
        check_pool_info(pool_info, "Name", result.stdout.strip())

        # Step (19)
        # Pool refresh for 'dir' type pool
        if pool_type == "dir":
            os.mknod(vol_path)
            result = virsh.pool_refresh(pool_name)
            check_exit_status(result)
            check_vol_list(vol_name, pool_name)

        # Step(20)
        # Pool destroy
        if virsh.pool_destroy(pool_name):
            logging.debug("Pool %s destroyed.", pool_name)
        else:
            raise error.TestFail("Destroy pool % failed." % pool_name)

        # Step (21)
        # Pool delete for 'dir' type pool
        if pool_type == "dir":
            if os.path.exists(vol_path):
                os.remove(vol_path)
            result = virsh.pool_delete(pool_name, ignore_status=True)
            check_exit_status(result)
            option = "--inactive --type %s" % pool_type
            check_pool_list(pool_name, option)
            if os.path.exists(pool_target):
                raise error.TestFail("The target path '%s' still exist." %
                                     pool_target)
            result = virsh.pool_start(pool_name, ignore_status=True)
            check_exit_status(result, True)

        # Step (22)
        # Pool undefine
        result = virsh.pool_undefine(pool_name, ignore_status=True)
        check_exit_status(result)
        check_pool_list(pool_name, "--all", True)
    finally:
        # Clean up
        if os.path.exists(pool_xml):
            os.remove(pool_xml)
        if not _pool.delete_pool(pool_name):
            logging.error("Can't delete pool: %s", pool_name)
        if cleanup_env[2]:
            cmd = "pvs |grep %s |awk '{print $1}'" % vg_name
            pv_name = utils.system_output(cmd)
            lv_utils.vg_remove(vg_name)
            utils.run("pvremove %s" % pv_name)
        if cleanup_env[1]:
            utils_test.libvirt.setup_or_cleanup_iscsi(False)
        if cleanup_env[0]:
            utils_test.libvirt.setup_or_cleanup_nfs(
                False, restore_selinux=cleanup_env[3])
