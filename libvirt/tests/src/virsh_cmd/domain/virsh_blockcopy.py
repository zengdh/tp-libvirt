import logging
import os
import time
import re
from autotest.client.shared import error
from virttest import utils_libvirtd, virsh, qemu_storage, data_dir
from virttest.libvirt_xml import vm_xml
from virttest.utils_test import libvirt as utl
from provider import libvirt_version


class JobTimeout(Exception):

    """
    Blockjob timeout in given time.
    """

    def __init__(self, timeout):
        Exception.__init__(self)
        self.timeout = timeout

    def __str__(self):
        return "Block job timeout in %s seconds." % self.timeout


def check_xml(vm_name, target, dest_path, blk_options):
    """
    Check the domain XML for blockcopy job

    :param vm_name: Domain name
    :param target: Domain disk target device
    :param dest_path: Path of the copy to create
    :param blk_options: Block job command options
    """
    re1 = 0
    re2 = 0
    # set expect result
    if blk_options.count("--finish"):
        # no <mirror> element and can't find dest_path in vm xml
        expect_re = 0
    elif blk_options.count("--pivot"):
        # no <mirror> element, but can find dest_path in vm xml
        expect_re = 1
    else:
        # find <mirror> element and dest_path in vm xml
        expect_re = 2

    blk_list = vm_xml.VMXML.get_disk_blk(vm_name)
    disk_list = vm_xml.VMXML.get_disk_source(vm_name)
    dev_index = 0
    try:
        try:
            dev_index = blk_list.index(target)
            disk_src = disk_list[dev_index].find('source').get('file')
            if disk_src == dest_path:
                logging.debug("Disk source change to %s.", dest_path)
                re1 = 1
            disk_mirror = disk_list[dev_index].find('mirror')
            if disk_mirror is not None:
                # Prior to 1.2.6 - <mirror> was a subelement of the <disk>
                # with the disk_mirror_src file found as an attribute. As of
                # 1.2.6 the output only XML changed to utilize a <source>
                # sublement where <mirror> now has a "type" attribute and
                # <source> format/output depends on the mirror type value.
                # Although for a brief period of time between commit id
                # '7c6fc394' and 'b50e1049', the file="/path/to/file"
                # attribute was removed from the <mirror> element. This
                # test failing here resulted in the file attribute being
                # restored for a type="file" only <mirror> to avoid a possible
                # regression for other users/parsers that expected the XML
                # to have the "file" attribute in a <mirror> element.
                if libvirt_version.version_compare(1, 2, 6):
                    mirror_type = disk_mirror.get('type')
                    disk_mirror_source = disk_mirror.find('source')
                    #
                    # Because we want to use the new and preferred syntax,
                    # let's do so for any libvirt 1.2.6 and beyond...
                    #
                    # Mirror type (currently) can be file, block, or network.
                    # For now the test only handles "file". In the future it
                    # could be augmented to handle other types.
                    #
                    # For mirror_type == "file" means <source> uses file=
                    # even though the "file" attribute does exist in the
                    # <mirror> element.
                    #
                    # For mirror_type == "block" means <source> uses dev=
                    #
                    # When mirror_type == "network" is supported <source>
                    # will be defined...
                    #
                    if mirror_type == "file" and disk_mirror_source is not None:
                        disk_mirror_src = disk_mirror_source.get('file')
                    else:
                        disk_mirror_src = None
                else:
                    disk_mirror_src = disk_mirror.get('file')
                if disk_mirror_src == dest_path:
                    logging.debug("Find %s in <mirror> element.", dest_path)
                    re2 = 2
        except Exception, detail:
            logging.error(detail)
    finally:
        if re1 + re2 == expect_re:
            logging.debug("Domain XML check pass.")
        else:
            raise error.TestFail("Domain XML check fail.")


def finish_job(vm_name, target, timeout):
    """
    Make sure the block copy job finish.

    :param vm_name: Domain name
    :param target: Domain disk target dev
    :param timeout: Timeout value of this function
    """
    job_time = 0
    while job_time < timeout:
        if utl.check_blockjob(vm_name, target, "progress", "100"):
            logging.debug("Block job progress up to 100%.")
            break
        else:
            job_time += 2
            time.sleep(2)
    if job_time >= timeout:
        raise JobTimeout(timeout)


def run(test, params, env):
    """
    Test command: virsh blockcopy.

    This command can copy a disk backing image chain to dest.
    1. Positive testing
        1.1 Copy a disk to a new image file.
        1.2 Reuse existing destination copy.
        1.3 Valid blockcopy timeout and bandwidth test.
    2. Negative testing
        2.1 Copy a disk to a non-exist directory.
        2.2 Copy a disk with invalid options.
        2.3 Do block copy for a persistent domain.
    """

    vm_name = params.get("main_vm")
    vm = env.get_vm(vm_name)
    target = params.get("target_disk", "")
    # check the source disk
    if not target:
        raise error.TestFail("Require target disk to copy")
    if vm_xml.VMXML.check_disk_exist(vm_name, target):
        logging.debug("Find %s in domain %s.", target, vm_name)
    else:
        raise error.TestFail("Can't find %s in domain %s." % (target, vm_name))
    dest_path = params.get("dest_path", "")
    dest_format = params.get("dest_format", "")
    # Ugh... this piece of chicanery brought to you by the QemuImg which
    # will "add" the 'dest_format' extension during the check_format code.
    # So if we create the file with the extension and then remove it when
    # doing the check_format later, then we avoid erroneous failures.
    dest_extension = ""
    if dest_format != "":
        dest_extension = ".%s" % dest_format
    if not dest_path:
        tmp_file = time.strftime("%Y-%m-%d-%H.%M.%S.img")
        tmp_file += dest_extension
        dest_path = os.path.join(data_dir.get_tmp_dir(), tmp_file)
    options = params.get("blockcopy_options", "")
    bandwidth = params.get("blockcopy_bandwidth", "")
    default_timeout = params.get("default_timeout", "300")
    reuse_external = "yes" == params.get("reuse_external", "no")
    persistent_vm = params.get("persistent_vm", "no")
    status_error = "yes" == params.get("status_error", "no")
    rerun_flag = 0

    # Prepare transient/persistent vm
    original_xml = vm.backup_xml()
    if persistent_vm == "no" and vm.is_persistent():
        vm.undefine()
    elif persistent_vm == "yes" and not vm.is_persistent():
        vm.define(original_xml)

    # Prepare for --reuse-external option
    if reuse_external:
        options += "--reuse-external"
        # Set rerun_flag=1 to do blockcopy twice, and the first time created
        # file can be reused in the second time if no dest_path given
        # This will make sure the image size equal to original disk size
        if dest_path == "/path/non-exist":
            if os.path.exists(dest_path) and not os.path.isdir(dest_path):
                os.remove(dest_path)
        else:
            rerun_flag = 1

    # Prepare other options
    if dest_format == "raw":
        options += "--raw"
    if len(bandwidth):
        options += "--bandwidth %s" % bandwidth

    # Prepare acl options
    uri = params.get("virsh_uri")
    unprivileged_user = params.get('unprivileged_user')
    if unprivileged_user:
        if unprivileged_user.count('EXAMPLE'):
            unprivileged_user = 'testacl'

    if not libvirt_version.version_compare(1, 1, 1):
        if params.get('setup_libvirt_polkit') == 'yes':
            raise error.TestNAError("API acl test not supported in current"
                                    + " libvirt version.")

    def check_format(dest_path, dest_extension, expect):
        """
        Check the image format

        :param dest_path: Path of the copy to create
        :param expect: Expect image format
        """
        # And now because the QemuImg will add the extension for us
        # we have to remove it here.
        path_noext = dest_path.strip(dest_extension)
        params['image_name'] = path_noext
        params['image_format'] = expect
        image = qemu_storage.QemuImg(params, "/", path_noext)
        if image.get_format() == expect:
            logging.debug("%s format is %s.", dest_path, expect)
        else:
            raise error.TestFail("%s format is not %s." % (dest_path, expect))

    # Run virsh command
    try:
        if rerun_flag == 1:
            options1 = "--wait --raw --finish --verbose"
            cmd_result = virsh.blockcopy(vm_name, target, dest_path, options1,
                                         unprivileged_user=unprivileged_user,
                                         uri=uri,
                                         ignore_status=True, debug=True)
            status = cmd_result.exit_status
            if status != 0:
                raise error.TestFail("Run blockcopy command fail.")
            elif not os.path.exists(dest_path):
                raise error.TestFail("Cannot find the created copy.")

        cmd_result = virsh.blockcopy(vm_name, target, dest_path, options,
                                     unprivileged_user=unprivileged_user,
                                     uri=uri,
                                     ignore_status=True, debug=True)
        status = cmd_result.exit_status
    except Exception, detail:
        logging.error(detail)

    if not utils_libvirtd.libvirtd_is_running():
        raise error.TestFail("Libvirtd service is dead.")
    # Check_result
    try:
        try:
            if not status_error:
                if status == 0:
                    check_xml(vm_name, target, dest_path, options)
                    if options.count("--bandwidth"):
                        utl.check_blockjob(vm_name, target, "bandwidth", bandwidth)
                    if options.count("--pivot") + options.count("--finish") == 0:
                        finish_job(vm_name, target, default_timeout)
                    if options.count("--raw"):
                        check_format(dest_path, dest_extension, dest_format)
                else:
                    raise error.TestFail(cmd_result.stderr)
            else:
                if status:
                    logging.debug("Expect error: %s", cmd_result.stderr)
                else:
                    # Commit id '4c297728' changed how virsh exits when
                    # unexpectedly failing due to timeout from a fail (1)
                    # to a success(0), so we need to look for a different
                    # marker to indicate the copy aborted
                    if options.count("--timeout") and \
                            options.count("--wait") and \
                            re.search("Copy aborted", cmd_result.stdout):
                        logging.debug("Found success a timed out block copy")
                    else:
                        raise error.TestFail("Expect fail, but run successfully.")
        except JobTimeout, excpt:
            if not status_error:
                raise error.TestFail("Run command failed: %s" % excpt)
    finally:
        if vm.is_alive():
            vm.destroy()
            virsh.define(original_xml)
        if os.path.exists(dest_path):
            os.remove(dest_path)
