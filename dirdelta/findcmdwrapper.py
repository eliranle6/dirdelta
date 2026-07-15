import subprocess


def find_files(rootpath, max_depth=None, file_extentions=None, include_hidden=True):
    command = _get_base_command(rootpath)
    if max_depth is not None:
        command.extend(["-maxdepth", str(max_depth)])
    if file_extentions is not None:
        command.append("-regex")
        addition = ".*." + "\|.*.".join(file_extentions)
        command.append(addition)
    command += ["-type", "f"]
    if not include_hidden:
        command += ['-not', '-path', '*/\\.*']
    return _get_command_output(command)


def find_dirs(rootpath, max_depth, include_hidden=True):
    command = _get_base_command(rootpath)
    if max_depth is not None:
        command.extend(["-maxdepth", str(max_depth)])
    command += ["-type", "d"]
    if not include_hidden:
        command += ['-not', '-path', '*/\\.*']
    return _get_command_output(command)


def _get_base_command(rootpath):
    return ["find", rootpath]


def _get_command_output(command):
    proc = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    output, _ = proc.communicate()
    output = output.decode('utf-8')
    return output.splitlines()
