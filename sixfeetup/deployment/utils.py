from fabric import api
from fabric import contrib
from fabric.operations import _shell_escape
from fabric.state import output

TRUISMS = [
    "true",
    "1",
    "yes",
    "y",
    "on",
    "sure",
]
GLOBAL_IGNORES = ['.svn', 'CVS', '.AppleDouble', '.git']
YES_OR_NO = ['yes', 'y', 'no', 'n']


def _quiet_remote_ls(path, fname_filter):
    with api.settings(api.hide('warnings', 'running', 'stdout', 'stderr'),
                  warn_only=True):
        with api.cd(path):
            return api.run('ls %s' % fname_filter)


def _quiet_remote_mkdir(path):
    if contrib.files.exists(path):
        return
    with api.settings(api.hide('warnings', 'running', 'stdout', 'stderr'),
                  warn_only=True):
        return api.sudo('mkdir -p %s' % path)


def _sshagent_run(command, shell=True, pty=True):
    """
    Helper function.
    Runs a command with SSH agent forwarding enabled.

    Note:: Fabric (and paramiko) can't forward your SSH agent.
    This helper uses your system's ssh to do so.
    """
    real_command = command
    if shell:
        cwd = api.env.get('cwd', '')
        if cwd:
            cwd = 'cd %s && ' % _shell_escape(cwd)
        real_command = '%s "%s"' % (api.env.shell,
            _shell_escape(cwd + real_command))
    if output.debug:
        print("[%s] run: %s" % (api.env.host_string, real_command))
    elif output.running:
        print("[%s] run: %s" % (api.env.host_string, command))
    with api.settings(api.hide('warnings', 'running', 'stdout', 'stderr'),
                  warn_only=True):
        return api.local(
            "ssh -A %s '%s'" % (api.env.host_string, real_command))
