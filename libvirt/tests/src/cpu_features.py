import os
import re
import shutil
import time

from autotest.client import os_dep, utils
from autotest.client.shared import error
from virttest.utils_test import libvirt as utlv

global is_mig_success
is_mig_success = False

def _nbench_help():
    """
    Execute ./nbench --help to verify nbench is available on this host.
    """
    result = utils.run("./nbench --help", ignore_status=True)
    if result.exit_status:
        return True
    return False

def find_index_values(filename):
    """
    Find the 'INTEGER INDEX' and 'FLOATING-POINT INDEX' in the result file.

    :RETURN (integer_index, floating_point_index)
    :RAISE TestFail if not all symbol present
    """
    with open(filename) as result_file:
        content = result_file.read()
        match_integer = re.search(r'(?<=INTEGER INDEX)(.*\d*\.\d*)',content)
        match_floating = re.search(r'(?<=FLOATING-POINT INDEX)(.*\d*\.\d*)',content)
        if match_integer is None or match_floating is None:
            raise error.TestFail("Failed to find INTEGER INDEX or "
                                 "FLOATING-POINT INDEX")

        integer_index = match_integer.group(0)
        integer_index = integer_index.split(":")[1].lstrip()
        floating_index = match_floating.group(0)
        floating_index = floating_index.split(":")[1].lstrip()

        return (float(integer_index), float(floating_index))

def cleanup_dest(vm, src_uri, dest_uri):
    """
    Cleanup migrated guest on destination.
    Then reset connect uri to src_uri
    """
    vm.connect_uri = dest_uri
    if vm.exists():
        if vm.is_persistent():
            vm.undefine()
        if vm.is_alive():
            vm.destroy()
    # Set connect uri back to local uri
    vm.connect_uri = src_uri

def thread_func_live_migration(vm, dest_uri, dargs):
    """
    Thread for virsh migrate command.
    """
    # Migrate the domain.
    debug = dargs.get("debug", "False")
    ignore_status = dargs.get("ignore_status", "False")
    options = "--live"
    extra = dargs.get("extra")
    global is_mig_success
    result = vm.migrate(dest_uri, options, extra, ignore_status, debug)
    if result.exit_status:
        return
    is_mig_success = True

def run(test, params, env):
    """
    Test for cpu features

    1) Check the nbench on host.
    2) Get variables.
    3) run nbench on host or
       try migration according to different cases. 
    4) Verify the result.
       compare nbench results of two hosts or
       check migration result according to different cases.
    4) Cleanup.
    """
    if not _nbench_help:
        raise error.TestNAError("No nbench found in host").

    dir_of_nbench = params.get('dir_of_nbench')
    mig_thread_timeout = params.get('mig_thread_timeout', 180)
    #vms
    vm_name_hv_default = params.get("hv_default")
    vm_name_nearest_host = params.get("nearest_host")
    vm_name_copy_host = params.get("copy_host")
    if vm_name_copy_host.count('ENTER') or vm_name_nearest_host.count('ENTER') or
       vm_name_hv_default.count('ENTER'):
        raise error.TestNAError('Please enter host names in .cfg files') 

    #test branches
    is_hv_default == ("yes" == params.get("cpu_features_hypervisor_default"));
    is_nearest_host == ("yes" == params.get("cpu_features_nearest_host"));
    is_copy_host == ("yes" == params.get("cpu_features_copy_host"));

    #prepare files for results
    hv_default_result_file = os.path.join(test.tmpdir, "hv_default_result")
    nearest_host_result_file = os.path.join(test.tmpdir, "nearest_host_result")
    copy_host_result_file = os.path.join(test.tmpdir, "copy_host_result")
    result_on_guest = "/root/result"

    try:
        if is_hv_default:
            guest_command = "cd %s; ./nbench > %s" % (dir_of_nbench, result_on_guest)

            vm_hv_default = env.get_vm(vm_name_hv_default)
            session_hv_default = vm_hv_default.wait_for_login()
            session_hv_default.cmd_status_output(guest_command)
            session_hv_default.close()
            vm.copy_files_from(result_on_guest, hv_default_result_file)
            ii_hv_default, fi_hv_default = find_index_values(hv_default_result_file)

            if is_nearest_host:
                vm_nearest_host = env.get_vm(vm_name_nearest_host)
                session_nearest_host = vm_nearest_host.wait_for_login()
                session_nearest_host.cmd_status_output(guest_command)
                session_nearest_host.close()
                vm.copy_files_from(result_on_guest, nearest_host_result_file)
                ii_nearest_host, fi_nearest_host = find_index_values(nearest_host_result_file)

                hv_is_slower = ii_hv_default < ii_nearest_host and 
                               fi_hv_default < fi_nearest_host
                if not hv_is_slower:
                    raise error.TestFail("hv_default's performance is better than nearest_host."
                                         "hv_default's result is (%s,%s), nearest_host's result is (%s,%s)."
                                         % (ii_hv_default, fi_hv_default, ii_nearest_host, fi_nearest_host))
            elif is_copy_host:
                vm_copy_host = env.get_vm(vm_name_copy_host)
                session_copy_cpu = vm_copy_cpu.wait_for_login()
                session_copy_cpu.cmd_status_output(guest_command)
                session_copy_cpu.close()
                vm.copy_files_from(result_on_guest, copy_cpu_result_file)
                ii_copy_cpu, fi_copy_cpu = find_index_values(copy_cpu_result_file)

                hv_is_slower = ii_hv_default < ii_copy_cpu and 
                               fi_hv_default < fi_copy_cpu
                if not hv_is_slower:
                    raise error.TestFail("hv_default's performance is better than copy_cpu."
                                         "hv_default's result is (%s,%s), copy_cpu's result is (%s,%s)."
                                         % (ii_hv_default, fi_hv_default, ii_copy_cpu, fi_copy_cpu))

        if not is_hv_default:
            #need migration
            src_uri = params.get("migrate_src_uri", "qemu+ssh://EXAMPLE/system")
            dest_uri = params.get("migrate_dest_uri", "qemu+ssh://EXAMPLE/system")
            if is_nearest_host:
                vm = env.get_vm(vm_name_nearest_host)   //TODO
            elif is_copy_host:
                vm = env.get_vm(vm_name_copy_host)   //TODO
            vm.wait_for_login()
            migrate_dargs = {'debug': True, 'ignore_status': True}

            try:
                mig_thread = threading.Thread(target=thread_func_live_migration,
                                              args=(vm, dest_uri,
                                                    migrate_dargs)))
                mig_thread.start()
                thread.join(mig_thread_timeout)

            finally:
                cleanup_dest(vm, src_uri, dest_uri)

            if is_nearest_host:
                if not is_mig_success:
                    raise error.TestFail("Migration failed.")
            elif is_copy_host:
                if is_mig_success:
                    raise error.testFail("Migration should fail, but successed")

    finally:
        if os.path.exists(hv_default_result_file):
            os.remove(hv_default_result_file)
        if os.path.exists(nearest_host_result_file):
            os.remove(nearest_host_result_file)
        if os.path.exists(copy_host_result_file):
            os.remove(copy_host_result_file)
