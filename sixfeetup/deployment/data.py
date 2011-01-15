import os
import datetime
from fabric import api
from sixfeetup.deployment.utils import (_quiet_remote_ls,
                                        _quiet_remote_mkdir,
                                        _sshagent_run)


DATA_HELP_TEXT = """
----------------------------------------------------------------

Current saved data files:

%(current_data_string)s

Enter a file name to %(saved_data_action)s:"""


def _get_data_path():
    if api.env.full_data_path:
        full_path = api.env.full_data_path
    else:
        full_path = os.path.join(
            api.env.base_data_path, api.env.project_name,
            'data')
    return full_path


def list_saved_data(fname_filter='*.tgz'):
    """List saved data files from the data server
    """
    full_path = _get_data_path()
    path_filter = os.path.join(full_path, fname_filter)
    for host in api.env.data_hosts:
        api.puts('%s: "%s"' % (host, path_filter))
        with api.settings(host_string=host):
            current_files = _quiet_remote_ls(full_path, fname_filter)
            api.puts(current_files)
            return current_files.split()


def _get_data_fname(saved_data_action='retrieve'):
   hide_levels = ['warnings', 'running', 'stdout', 'stderr',
                  'user']
   with api.settings(api.hide(*hide_levels), warn_only=True):
       current_data = list_saved_data()
       current_data_string = '\t' + '\n\t'.join(current_data)
       most_recent_data = current_data[-1]
   help_txt = DATA_HELP_TEXT % locals()
   return api.prompt(help_txt, default=most_recent_data)


def get_saved_data(fname=None):
    """Retrieve a saved data file from the data server
    """
    for host in api.env.data_hosts:
        with api.settings(host_string=host):
            if fname is None:
                fname = _get_data_fname()
            api.get(os.path.join(_get_data_path(), fname), fname)


def push_saved_data_to_qa(fname=None):
    """Push a saved data file to QA
    """
    qa_path = os.path.join(api.env.base_qa_path, api.env.project_name, 'var')
    for data_host in api.env.data_hosts:
        with api.settings(host_string=data_host):
            if fname is None:
                fname = _get_data_fname('push')
            fpath = os.path.join(_get_data_path(), fname)
            for qa_host in api.env.qa_hosts:
                with api.settings(host_string=qa_host, warn_only=True):
                    cmd = 'scp %s:%s %s' % (data_host, fpath, qa_path)
                    _sshagent_run(cmd)


def _sync_datafs(host_type, path):
    data_host = api.env.data_hosts[0]
    src_path = os.path.join(path, 'var', 'filestorage', 'Data.fs')
    src_host_string = ':'.join([api.env.host_string, src_path])
    target_path = os.path.join(api.env.base_data_path,
                               api.env.project_name,
                               'data', 'current_prod')
    today = datetime.date.today().strftime('%Y-%m-%d')
    filename_test = 'Data.fs-%s-%s-%s-*.tgz' % (api.env.project_name,
                                                host_type,
                                                today)
    data_path = _get_data_path()
    result = _quiet_remote_ls(data_path, filename_test)
    existing_files = result.split()
    filename = 'Data.fs-%s-%s-%s-%02d.tgz' % (api.env.project_name,
                                              host_type,
                                              today,
                                              len(existing_files)+1)
    # Ensure the `current_prod` dir exists
    result = _quiet_remote_mkdir(target_path)
    with api.settings(host_string=data_host):
        _sshagent_run('rsync -z --inplace %s %s' % (src_host_string,
                                                   target_path))
        with api.cd(target_path):
            result = api.run('tar czf %s Data.fs' % filename)
            if result.succeeded:
                api.run('mv %s ..' % filename)
            else:
                api.run('rm -f %s' % filename)


def sync_data(role='prod', data_type='Data.fs'):
    """Retrieve a set of data from either prod or staging.
    """
    # Basic sanity checks
    if role not in ['prod', 'staging']:
        api.abort('Role must be either "prod" or "staging".')
    if data_type != 'Data.fs':
        api.abort('The only supported data_type is "Data.fs".')

    api.puts('Retrieving the %s for %s' % (data_type, role))

    hosts = api.env.get('%s_hosts' % role)
    base_path = api.env.get('base_%s_path' % role)
    project_path = os.path.join(base_path,
                                api.env.project_name)
    for host in hosts:
        with api.settings(host_string=host):
            if data_type == 'Data.fs':
                _sync_datafs(role, project_path)
