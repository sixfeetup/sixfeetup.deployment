import os
import pickle
import re
import datetime
import distutils.version
from fabric import colors
from fabric import api
from fabric import contrib
from fabric.operations import _shell_escape
from fabric.state import output
import py.path

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
PASS_ME = ['none', 'skip', 's']
SETUPPY_VERSION = r"""(version.*=.*['"])(.*)(['"])"""
DIFF_HELP_TEXT = """
----------------------------------------------------------------

Current tags:
    %(current_tags_string)s
Select a tag to compare with the current version, you can (s)kip
%(package)s"""
TAG_HELP_TEXT = """
----------------------------------------------------------------

Current tags:
    %(current_tags_string)s
Enter a tag name for %(package)s"""
DATA_HELP_TEXT = """
----------------------------------------------------------------

Current saved data files:

%(current_data_string)s

Enter a file name to %(saved_data_action)s:"""

# URL to the trac instance base
api.env.trac_url_base = 'https://trac.sixfeetup.com'
# This is the trac/svn/dist/extranet name
api.env.project_name = ""
# List of package paths
# XXX: this shouldn't have to be paths...
api.env.packages = []
# Default release target. This is a jarn.mkrelease target name
api.env.default_release_target = 'public'
# The default path and regex for version number changing
api.env.default_version_location = ['setup.py', SETUPPY_VERSION]
# location of the versions.cfg file
api.env.versions_cfg_location = "profiles/versions.cfg"
# List of packages to release
api.env.to_release = []
# This is a directory that contains the eggs we want to release
api.env.package_dirs = ['src']
# List of package path names to ignore (e.g. 'my.package')
api.env.ignore_dirs = []
# extra information for a package
api.env.package_info = {}
# QA server host
api.env.qa_hosts = ["sfupqaapp01"]
api.env.staging_hosts = ["sfupstaging01"]
api.env.prod_hosts = []
# Data server host
api.env.data_hosts = ['extranet']
# Data base path
api.env.base_data_path = '/usr/local/www/data'
api.env.full_data_path = ''
# Base path to instances
api.env.base_qa_path = "/var/db/zope/dev"
api.env.base_staging_path = "/var/db/zope"
api.env.base_prod_path = "/var/db/zope"
# actual name of the buildout directory
api.env.qa_buildout_name = ""
api.env.staging_buildout_name = ""
api.env.prod_buildout_name = ""
# supervisor process names
api.env.qa_supervisor_processes = ""
api.env.staging_supervisor_processes = ""
api.env.prod_supervisor_processes = ""
# tag number
api.env.deploy_tag = ""


def deploy(env='qa', diffs='on'):
    """Start the deployment process for this project
    """
    _release_manager_warning()
    if env == 'qa':
        choose_packages(diffs, save_choices='yes')
        release_packages(save_choices='yes')
        bump_package_versions()
        update_versions_cfg()
        tag_buildout()
        release_qa()
    else:
        eval("release_%s()" % env)
    _clear_previous_state()
    _release_manager_warning()


def _release_manager_warning():
    print """
%s

Check the following URL before continuing:
%s/%s/%s
""" % (colors.red("Are there any release manager tickets?", bold=True),
       api.env.trac_url_base,
       api.env.project_name,
       "query?status=awaiting+release+action")
    api.prompt("Press return to continue")


def list_package_candidates(verbose='yes'):
    """List the packages that are available for deployment"""
    ignore_dirs = api.env.ignore_dirs + GLOBAL_IGNORES
    # find all the packages in the given package dirs
    for package_dir in api.env.package_dirs:
        items = os.listdir(package_dir)
        for item in items:
            if item not in ignore_dirs:
                package_path = '%s/%s' % (package_dir, item)
                if os.path.isdir(package_path):
                    with api.cd(package_path):
                        # get the actual package name from the setup.py
                        package_name = api.local("python setup.py --name")
                    if not package_name in api.env.package_info:
                        api.env.package_info[package_name] = {}
                    api.env.package_info[package_name]['path'] = package_path
                    api.env.packages.append(package_name)
    if verbose.lower() in TRUISMS:
        print """
Packages available:
%s
""" % "\n".join(api.env.packages)


def _find_tags_url(wc):
    """Find the wcpath/tags/ url so we can tag the package
    """
    url = wc.url.strip('/')
    url_parts = url.split('/')
    base_name = wc.svnurl().basename
    if base_name != 'trunk':
        # XXX this is a bit presumptuous
        # remove the branches or tags
        del url_parts[-2]
    url_parts.remove(base_name)
    base_url = '/'.join(url_parts)
    return py.path.svnurl("%s/tags" % base_url)


def _load_previous_state(save_choices):
    """Get state info from the saved pickle
    """
    msg = "Do you want to use the previously saved choices?"
    if (save_choices and
      os.path.exists('.saved_choices') and
      contrib.console.confirm(msg)):
        with open('.saved_choices') as f:
            api.env.package_info = pickle.load(f)
            api.env.to_release = [
                package
                for package in api.env.package_info
                if api.env.package_info[package].get('release', False)]
        return True
    elif os.path.exists('.saved_choices'):
        os.unlink('.saved_choices')
    return False


def _clear_previous_state():
    if not os.path.exists('.saved_choices'):
        return
    os.unlink('.saved_choices')


def choose_packages(show_diff='yes', save_choices='no'):
    """Choose the packages that need to be released"""
    save_choices = save_choices.lower() in TRUISMS
    if _load_previous_state(save_choices):
        return
    list_package_candidates()
    for package in api.env.packages:
        wc = py.path.svnwc(api.env.package_info[package]['path'])
        wc_url = wc.url
        if show_diff.lower() in TRUISMS:
            tags_url = _find_tags_url(wc)
            # XXX: kind of silly here...
            current_tags = map(
                lambda x: distutils.version.LooseVersion(x.basename),
                tags_url.listdir())
            current_tags.sort()
            current_tags = map(str, current_tags)
            current_tags_string = "No tags created yet"
            if current_tags:
                current_tags_string = "\n    ".join(current_tags)
            cmp_tag = None
            while True:
                help_txt = DIFF_HELP_TEXT % locals()
                default_tag = 'None'
                if len(current_tags) > 0:
                    default_tag = current_tags[-1]
                cmp_tag = api.prompt(help_txt, default=default_tag)
                if cmp_tag.lower() in PASS_ME or cmp_tag in current_tags:
                    break
            if cmp_tag.lower() not in PASS_ME:
                cmd = 'svn diff %(tags_url)s/%(cmp_tag)s %(wc_url)s |colordiff'
                print api.local(cmd % locals())
        while True:
            release_package = api.prompt(
                "Does '%s' need a release?" % package, default="no").lower()
            if release_package in TRUISMS:
                api.env.package_info[package]['release'] = True
                api.env.to_release.append(package)
            # make sure the question was answered properly
            if release_package in YES_OR_NO:
                break
    if save_choices:
        with open('.saved_choices', 'w') as f:
            pickle.dump(api.env.package_info, f)


def _next_minor_version(version_string):
    parts = version_string.split('.')
    minor = int(parts.pop())
    parts.append(str(minor + 1))
    return '.'.join(parts)


def release_packages(verbose="no", dev="no", save_choices='no'):
    save_choices = save_choices.lower() in TRUISMS
    if not api.env.to_release:
        print colors.yellow("\nNo packages to release.")
        return
    print colors.blue("\nReleasing packages")
    print "\n".join(api.env.to_release) + "\n"
    for package in api.env.to_release:
        package_info = api.env.package_info[package]
        # first check to see if this version of the package was already
        # released
        current_release = package_info.get('released_version', None)
        with api.cd(package_info['path']):
            current_version = api.local("python setup.py --version")
        if current_release is not None and current_release == current_version:
            msg = "%s version %s has already been released"
            print colors.red(msg % (package, current_version))
            # since it was already release, just move on to the next package
            continue
        package_path = package_info['path']
        package_target = package_info.get(
            'target',
            api.env.default_release_target)
        cmd = "mkrelease %s -d %s %s"
        # TODO: handle dev release
        # TODO: alternate release targets (e.g. private)
        with api.settings(warn_only=True):
            output = api.local(
                cmd % ("-C", package_target, package_path))
        if output.failed:
            print output
            api.abort(output.stderr)
        # search through the mkrelease output to find the version number
        tag_output = re.search('Tagging %s (.*)' % package, output)
        if tag_output is not None and len(tag_output.groups()):
            package_version = tag_output.groups()[0]
        else:
            print output
            api.abort("Could not find package version from mkrelease output")
        api.env.package_info[package]['version'] = package_version
        api.env.package_info[package]['next_version'] = _next_minor_version(
            package_version)
        api.env.package_info[package]['released_version'] = package_version
        if save_choices:
            with open('.saved_choices', 'w') as f:
                pickle.dump(api.env.package_info, f)
        if verbose.lower() in TRUISMS:
            print output


def bump_package_versions():
    if not api.env.to_release:
        return
    print colors.blue("Bumping package versions")
    bumpers = [
        "%s %s" % (package, api.env.package_info[package]['next_version'])
        for package in api.env.package_info
        if api.env.package_info[package].get('release', False)]
    print "\n".join(bumpers)
    for package in api.env.to_release:
        package_info = api.env.package_info[package]
        next_version = package_info['next_version']
        version_location = package_info.get(
            'version_location',
            api.env.default_version_location)
        version_file = "%s/%s" % (package_info['path'], version_location[0])
        version_re = version_location[1]
        if os.path.exists(version_file):
            with open(version_file, 'r') as f:
                vf_contents = f.read()
            with open(version_file, 'w') as f:
                vf_new = re.sub(
                    version_re,
                    '\g<1>' + next_version + '\g<3>',
                    vf_contents,
                    re.M)
                f.write(vf_new)
            cmd = "svn ci -m 'bumping version for next release' %s"
            api.local(cmd % version_file)


def update_versions_cfg():
    """Update the versions.cfg with the packages that have changed
    """
    if not api.env.to_release:
        return
    print colors.blue("Updating versions.cfg")
    # get the version file contents
    v_cfg = api.env.versions_cfg_location
    with open(v_cfg) as f:
        vcfg_content = f.read()
    missing_versions = []
    # loop through the packages and update the versions
    with open(v_cfg, 'w') as f:
        for package in api.env.to_release:
            package_info = api.env.package_info[package]
            package_version = package_info['version']
            package_re = "%s.*" % package
            version_pins = re.findall(package_re, vcfg_content)
            if not version_pins:
                print colors.red(
                    '%s was not in versions.cfg. It was added.' % package)
                missing_versions.append('%s = %s' % (package, package_version))
            else:
                if len(version_pins) > 1:
                    print colors.red(
                        "WARNING: There were multiple pins for %s" % package)
                vcfg_content = re.sub(
                    package_re,
                    "%s = %s" % (package, package_version),
                    vcfg_content,
                    re.M)
        f.write(vcfg_content)
    # add any missing version definitions to the config file
    if missing_versions:
        with open(v_cfg, 'a') as f:
            for missing in missing_versions:
                f.write("%s\n" % missing)
    api.local("svn ci -m 'updating versions for release' %s" % v_cfg)


def _get_buildout_url():
    """Get the base buildout url
    """
    wc = py.path.svnwc('.')
    trunk_url = wc.url
    base_dir = wc.svnurl().dirpath().url
    return trunk_url, base_dir


def tag_buildout():
    if not api.env.to_release:
        return
    print colors.blue("Tagging buildout")
    trunk_url, base_dir = _get_buildout_url()
    with open('version.txt') as f:
        version = f.read().strip()
    api.local("svn cp -m 'tagging for release' %s %s/tags/%s" % (
        trunk_url, base_dir, version))
    # now bump the version and commit
    with open('version.txt', 'w') as f:
        new_version = _next_minor_version(version)
        f.write(new_version)
    api.env.deploy_tag = version
    api.local("svn ci -m 'bumping version for next release' version.txt")


def release_qa():
    print colors.blue("Releasing to QA")
    api.env.deploy_env = 'qa'
    for host in api.env.qa_hosts:
        with api.settings(host_string=host):
            _release_to_env()


def release_staging():
    print colors.blue("Releasing to staging")
    api.env.deploy_env = 'staging'
    for host in api.env.staging_hosts:
        with api.settings(host_string=host):
            _release_to_env()


def release_prod():
    print colors.blue("Releasing to prod")
    do_release = contrib.console.confirm("Are you sure?", default=False)
    if not do_release:
        api.abort("You didn't want to release")
    api.env.deploy_env = 'prod'
    for host in api.env.prod_hosts:
        with api.settings(host_string=host):
            _release_to_env()


def _release_to_env():
    """Release to a particular environment
    """
    base_env_path = "base_%s_path" % api.env.deploy_env
    base_path = api.env.get(base_env_path, "")
    if not base_path:
        api.abort("Couldn't find %s" % base_env_path)
    buildout_name = api.env.get("%s_buildout_name" % api.env.deploy_env, "")
    if not buildout_name:
        api.abort("Buildout name not defined for %s" % api.env.deploy_env)
    # check for the buildout
    buildout_dir = "%s/%s" % (base_path, buildout_name)
    trunk_url, base_url = _get_buildout_url()
    if not api.env.deploy_tag:
        # TODO: give the user a list of tags here
        api.env.deploy_tag = api.prompt("What tag do you want to release?")
    tag_url = "%s/tags/%s" % (base_url, api.env.deploy_tag)
    if not contrib.files.exists(buildout_dir):
        api.abort(
            "You need to create the initial api.env first: %s" % buildout_dir)
        # TODO: add to supervisor configs
        #with cd(base_path):
        #    api.run("svn co %s %s" % (tag_url, buildout_name))
        #    # TODO: make sure project is chowned and chmoded properly
        #with cd(buildout_dir):
        #    api.run("python%s bootstrap.py %s" % (
        #        api.env.python_version,
        #        api.env.bootstrap_args))
    supervisor_processes = api.env.get(
        "%s_supervisor_processes" % api.env.deploy_env,
        "")
    if not supervisor_processes:
        api.abort("Couldn't find supervisor process names")
    # stop instance
    api.run("supervisorctl stop %s" % supervisor_processes)
    # TODO: get the data from prod/staging here
    with api.cd(buildout_dir):
        # XXX: Why did we have to do this? login shell borks things
        api.env.shell = "/bin/bash -c"
        # TODO: Check for changes in the buildout
        # TODO: Make this work as a particular user (namely zope)
        # switch to the new tag
        api.run("svn switch %s" % tag_url)
        # TODO: check for issues with switch
        # run buildout
        api.run("bin/buildout -v")
    # start instance
    api.run("supervisorctl start %s" % supervisor_processes)


def _get_data_path():
    if api.env.full_data_path:
        full_path = api.env.full_data_path
    else:
        full_path = os.path.join(
            api.env.base_data_path, api.env.project_name,
            'data')
    return full_path


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


def _retrieve_datafs(host_type, path):
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


def retrieve_data(role='prod', data_type='Data.fs'):
    """Retrieve a set of data from either prod or staging.
    """
    api.puts('Retrieving the %s for %s' % (data_type, role))
    if role == 'prod':
        hosts = api.env.prod_hosts
        base_path = api.env.base_prod_path
    elif role == 'staging':
        hosts = api.env.staging_hosts
        base_path = api.env.base_staging_path
    else:
        api.abort('Role must be either "prod" or "staging".')
    if data_type != 'Data.fs':
        api.abort('The only supported data_type is "Data.fs".')
    project_path = os.path.join(base_path,
                                api.env.project_name)
    for host in hosts:
        with api.settings(host_string=host):
            if data_type == 'Data.fs':
                _retrieve_datafs(role, project_path)
