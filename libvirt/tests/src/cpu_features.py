import os
import re
import shutil
import time

from autotest.client import os_dep, utils
from autotest.client.shared import error

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
        integer_index = float(integer_index)
        floating_index = match_floating.group(0)
        floating_index = floating_index.split(":")[1].lstrip()
        floating_index = float(floating_index)

        return (integer_index, floating_index)

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
    #vms
    vm_name_hv_default = params.get("hv_default")
    vm_name_nearest_host = params.get("nearest_host")
    vm_name_copy_host = params.get("copy_host")
    if vm_name_copy_host.count('ENTER') or vm_name_nearest_host.count('ENTER')
       or vm_name_hv_default.count('ENTER'):
         raise error.TestNAError('Please enter host names in .cfg files') 
    vm_hv_default = env.get_vm(vm_name_hv_default)
    vm_nearest_host = env.get_vm(vm_name_nearest_host)
    vm_copy_host = env.get_vm(vm_name_copy_host)

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
        if is_hv_default and is_nearest_host:
            guest_command = "cd %s; ./nbench > %s" % (dir_of_nbench, result_on_guest)

            session_hv_default = vm_hv_default.wait_for_login()
            session_hv_default.cmd_status_output(guest_command)
            session_hv_default.close()
            vm.copy_files_from(result_on_guest, hv_default_result_file)
            ii_hv_default, fi_hv_default = find_index_values(hv_default_result_file)

            session_nearest_host = vm_nearest_host.wait_for_login()
            session_nearest_host.cmd_status_output(guest_command)
            session_nearest_host.close()
            vm.copy_files_from(result_on_guest, session_nearest_host)
            ii_nearest_host, fi_nearest_host = find_index_values(hv_default_result_file)

            hv_is_slower = ii_hv_default < ii_nearest_host and 
                           fi_hv_default < fi_nearest_host
            if not hv_is_slower:
                raise error.TestFail("hv_default's performance is better than nearest_host."
                                     "hv_default's result is (%s,%s), nearest_host's result is (%s,%s)."
                                     % (ii_hv_default, fi_hv_default, ii_nearest_host, fi_nearest_host))

        if is_hv_default and is_copy_host:
            #similar to the previous case, replace vm_nearest_cpu with vm_copy_cpu

        if (not is_hv_default) and is_nearest_host:
            #need migration

        if (not is_hv_default) and is_copy_host:
            #need migration

    finally:
        if os.path.exists(hv_default_result_file):
            os.remove(hv_default_result_file)
        if os.path.exists(nearest_host_result_file):
            os.remove(nearest_host_result_file)
        if os.path.exists(copy_host_result_file):
            os.remove(copy_host_result_file)
