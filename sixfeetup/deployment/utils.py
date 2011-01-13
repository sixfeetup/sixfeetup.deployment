from fabric import api
from fabric import contrib

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
