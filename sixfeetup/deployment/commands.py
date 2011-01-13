import os
import pickle
import re

from datetime import date

import distutils.version

from fabric import colors
from fabric.api import abort
from fabric.api import cd
from fabric.api import env
from fabric.api import get
from fabric.api import hide
from fabric.api import local
from fabric.api import prompt
from fabric.api import puts
from fabric.api import run
from fabric.api import settings
from fabric.contrib.console import confirm
from fabric.contrib.files import exists
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
env.trac_url_base = 'https://trac.sixfeetup.com'
# This is the trac/svn/dist/extranet name
env.project_name = ""
# List of package paths
# XXX: this shouldn't have to be paths...
env.packages = []
# Default release target. This is a jarn.mkrelease target name
env.default_release_target = 'public'
# The default path and regex for version number changing
env.default_version_location = ['setup.py', SETUPPY_VERSION]
# location of the versions.cfg file
env.versions_cfg_location = "profiles/versions.cfg"
# List of packages to release
env.to_release = []
# This is a directory that contains the eggs we want to release
env.package_dirs = ['src']
# List of package path names to ignore (e.g. 'my.package')
env.ignore_dirs = []
# extra information for a package
env.package_info = {}
# QA server host
env.qa_hosts = ["sfupqaapp01"]
env.staging_hosts = ["sfupstaging01"]
env.prod_hosts = []
# Data server host
env.data_hosts = ['extranet']
# Data base path
env.base_data_path = '/usr/local/www/data'
env.full_data_path = ''
# Base path to instances
env.base_qa_path = "/var/db/zope/dev"
env.base_staging_path = "/var/db/zope"
env.base_prod_path = "/var/db/zope"
# actual name of the buildout directory
env.qa_buildout_name = ""
env.staging_buildout_name = ""
env.prod_buildout_name = ""
# supervisor process names
env.qa_supervisor_processes = ""
env.staging_supervisor_processes = ""
env.prod_supervisor_processes = ""
# tag number
env.deploy_tag = ""

env.roledefs = {
    'qa': lambda x: env.qa_hosts,
}

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
       env.trac_url_base,
       env.project_name,
       "query?status=awaiting+release+action")
    prompt("Press return to continue")


def list_package_candidates(verbose='yes'):
    """List the packages that are available for deployment"""
    ignore_dirs = env.ignore_dirs + GLOBAL_IGNORES
    # find all the packages in the given package dirs
    for package_dir in env.package_dirs:
        items = os.listdir(package_dir)
        for item in items:
            if item not in ignore_dirs:
                package_path = '%s/%s' % (package_dir, item)
                if os.path.isdir(package_path):
                    with cd(package_path):
                        # get the actual package name from the setup.py
                        package_name = local("python setup.py --name")
                    if not package_name in env.package_info:
                        env.package_info[package_name] = {}
                    env.package_info[package_name]['path'] = package_path
                    env.packages.append(package_name)
    if verbose.lower() in TRUISMS:
        print """
Packages available:
%s
""" % "\n".join(env.packages)


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
    if (save_choices and
      os.path.exists('.saved_choices') and
      confirm("Do you want to use the previously saved choices?")):
        with open('.saved_choices') as f:
            env.package_info = pickle.load(f)
            env.to_release = [
                package
                for package in env.package_info
                if env.package_info[package].get('release', False)]
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
    for package in env.packages:
        wc = py.path.svnwc(env.package_info[package]['path'])
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
                cmp_tag = prompt(help_txt, default=default_tag)
                if cmp_tag.lower() in PASS_ME or cmp_tag in current_tags:
                    break
            if cmp_tag.lower() not in PASS_ME:
                cmd = 'svn diff %(tags_url)s/%(cmp_tag)s %(wc_url)s |colordiff'
                print local(cmd % locals())
        while True:
            release_package = prompt(
                "Does '%s' need a release?" % package, default="no").lower()
            if release_package in TRUISMS:
                env.package_info[package]['release'] = True
                env.to_release.append(package)
            # make sure the question was answered properly
            if release_package in YES_OR_NO:
                break
    if save_choices:
        with open('.saved_choices', 'w') as f:
            pickle.dump(env.package_info, f)


def _next_minor_version(version_string):
    parts = version_string.split('.')
    minor = int(parts.pop())
    parts.append(str(minor + 1))
    return '.'.join(parts)


def release_packages(verbose="no", dev="no", save_choices='no'):
    save_choices = save_choices.lower() in TRUISMS
    if not env.to_release:
        print colors.yellow("\nNo packages to release.")
        return
    print colors.blue("\nReleasing packages")
    print "\n".join(env.to_release) + "\n"
    for package in env.to_release:
        package_info = env.package_info[package]
        # first check to see if this version of the package was already
        # released
        current_release = package_info.get('released_version', None)
        with cd(package_info['path']):
            current_version = local("python setup.py --version")
        if current_release is not None and current_release == current_version:
            msg = "%s version %s has already been released"
            print colors.red(msg % (package, current_version))
            # since it was already release, just move on to the next package
            continue
        package_path = package_info['path']
        package_target = package_info.get('target', env.default_release_target)
        cmd = "mkrelease %s -d %s %s"
        # TODO: handle dev release
        # TODO: alternate release targets (e.g. private)
        with settings(warn_only=True):
            output = local(
                cmd % ("-C", package_target, package_path))
        if output.failed:
            print output
            abort(output.stderr)
        # search through the mkrelease output to find the version number
        tag_output = re.search('Tagging %s (.*)' % package, output)
        if tag_output is not None and len(tag_output.groups()):
            package_version = tag_output.groups()[0]
        else:
            print output
            abort("Could not find package version from mkrelease output")
        env.package_info[package]['version'] = package_version
        env.package_info[package]['next_version'] = _next_minor_version(
            package_version)
        env.package_info[package]['released_version'] = package_version
        if save_choices:
            with open('.saved_choices', 'w') as f:
                pickle.dump(env.package_info, f)
        if verbose.lower() in TRUISMS:
            print output


def bump_package_versions():
    if not env.to_release:
        return
    print colors.blue("Bumping package versions")
    bumpers = [
        "%s %s" % (package, env.package_info[package]['next_version'])
        for package in env.package_info
        if env.package_info[package].get('release', False)]
    print "\n".join(bumpers)
    for package in env.to_release:
        package_info = env.package_info[package]
        next_version = package_info['next_version']
        version_location = package_info.get(
            'version_location',
            env.default_version_location)
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
            local(cmd % version_file)


def update_versions_cfg():
    """Update the versions.cfg with the packages that have changed
    """
    if not env.to_release:
        return
    print colors.blue("Updating versions.cfg")
    # get the version file contents
    v_cfg = env.versions_cfg_location
    with open(v_cfg) as f:
        vcfg_content = f.read()
    missing_versions = []
    # loop through the packages and update the versions
    with open(v_cfg, 'w') as f:
        for package in env.to_release:
            package_info = env.package_info[package]
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
    local("svn ci -m 'updating versions for release' %s" % v_cfg)


def _get_buildout_url():
    """Get the base buildout url
    """
    wc = py.path.svnwc('.')
    trunk_url = wc.url
    base_dir = wc.svnurl().dirpath().url
    return trunk_url, base_dir


def tag_buildout():
    if not env.to_release:
        return
    print colors.blue("Tagging buildout")
    trunk_url, base_dir = _get_buildout_url()
    with open('version.txt') as f:
        version = f.read().strip()
    local("svn cp -m 'tagging for release' %s %s/tags/%s" % (
        trunk_url, base_dir, version))
    # now bump the version and commit
    with open('version.txt', 'w') as f:
        new_version = _next_minor_version(version)
        f.write(new_version)
    env.deploy_tag = version
    local("svn ci -m 'bumping version for next release' version.txt")


def release_qa():
    print colors.blue("Releasing to QA")
    env.deploy_env = 'qa'
    for host in env.qa_hosts:
        with settings(host_string=host):
            _release_to_env()


def release_staging():
    print colors.blue("Releasing to staging")
    env.deploy_env = 'staging'
    for host in env.qa_hosts:
        with settings(host_string=host):
            _release_to_env()


def release_prod():
    print colors.blue("Releasing to prod")
    do_release = confirm("Are you sure?", default=False)
    if not do_release:
        abort("You didn't want to release")
    env.deploy_env = 'prod'
    for host in env.qa_hosts:
        with settings(host_string=host):
            _release_to_env()


def _release_to_env():
    """Release to a particular environment
    """
    base_env_path = "base_%s_path" % env.deploy_env
    base_path = env.get(base_env_path, "")
    if not base_path:
        abort("Couldn't find %s" % base_env_path)
    buildout_name = env.get("%s_buildout_name" % env.deploy_env, "")
    if not buildout_name:
        abort("Buildout name not defined for %s" % env.deploy_env)
    # check for the buildout
    buildout_dir = "%s/%s" % (base_path, buildout_name)
    trunk_url, base_url = _get_buildout_url()
    if not env.deploy_tag:
        # TODO: give the user a list of tags here
        env.deploy_tag = prompt("What tag do you want to release?")
    tag_url = "%s/tags/%s" % (base_url, env.deploy_tag)
    if not exists(buildout_dir):
        abort("You need to create the initial env first: %s" % buildout_dir)
        # TODO: add to supervisor configs
        #with cd(base_path):
        #    run("svn co %s %s" % (tag_url, buildout_name))
        #with cd(buildout_dir):
        #    run("python%s bootstrap.py %s" % (
        #        env.python_version,
        #        env.bootstrap_args))
    supervisor_processes = env.get(
        "%s_supervisor_processes" % env.deploy_env,
        "")
    if not supervisor_processes:
        abort("Couldn't find supervisor process names")
    # stop instance
    run("supervisorctl stop %s" % supervisor_processes)
    # TODO: get the data from prod/staging here
    with cd(buildout_dir):
        # switch to the new tag
        run("svn switch %s" % tag_url)
        # XXX: check for issues with switch
        # run buildout
        run("bin/buildout -v")
    # start instance
    run("supervisorctl start %s" % supervisor_processes)


def _get_data_path():
    if env.full_data_path:
        full_path = env.full_data_path
    else:
        full_path = os.path.join(env.base_data_path, env.project_name, 'data')
    return full_path


def _quiet_remote_ls(path, fname_filter):
    with settings(hide('warnings', 'running', 'stdout', 'stderr'),
                  warn_only=True):
        with cd(path):
            return run('ls %s' % fname_filter)


def list_saved_data(fname_filter='*.tgz'):
    """List saved data files from the data server
    """
    full_path = _get_data_path()
    path_filter = os.path.join(full_path, fname_filter)
    for host in env.data_hosts:
        puts('%s: "%s"' % (host, path_filter))
        with settings(host_string=host):
            current_files = _quiet_remote_ls(full_path, fname_filter)
            puts(current_files)
            return current_files.split()


def _get_data_fname(saved_data_action='retrieve'):
   hide_levels = ['warnings', 'running', 'stdout', 'stderr',
                  'user']
   with settings(hide(*hide_levels), warn_only=True):
       current_data = list_saved_data()
       current_data_string = '\t' + '\n\t'.join(current_data)
       most_recent_data = current_data[-1]
   help_txt = DATA_HELP_TEXT % locals()
   return prompt(help_txt, default=most_recent_data)

def get_saved_data(fname=None):
    """Retrieve a saved data file from the data server
    """
    for host in env.data_hosts:
        with settings(host_string=host):
            if fname is None:
                fname = _get_data_fname()
            get(os.path.join(_get_data_path(), fname), fname)


def _sshagent_run(command, shell=True, pty=True):
    """
    Helper function.
    Runs a command with SSH agent forwarding enabled.

    Note:: Fabric (and paramiko) can't forward your SSH agent.
    This helper uses your system's ssh to do so.
    """
    real_command = command
    if shell:
        cwd = env.get('cwd', '')
        if cwd:
            cwd = 'cd %s && ' % _shell_escape(cwd)
        real_command = '%s "%s"' % (env.shell,
            _shell_escape(cwd + real_command))
    if output.debug:
        print("[%s] run: %s" % (env.host_string, real_command))
    elif output.running:
        print("[%s] run: %s" % (env.host_string, command))
    with settings(hide('warnings', 'running', 'stdout', 'stderr'),
                  warn_only=True):
        return local("ssh -A %s '%s'" % (env.host_string, real_command))


def push_saved_data_to_qa(fname=None):
    """Push a saved data file to QA
    """
    qa_path = os.path.join(env.base_qa_path, env.project_name, 'var')
    for data_host in env.data_hosts:
        with settings(host_string=data_host):
            if fname is None:
                fname = _get_data_fname('push')
            fpath = os.path.join(_get_data_path(), fname)
            for qa_host in env.qa_hosts:
                with settings(host_string=qa_host, warn_only=True):
                    cmd = 'scp %s:%s %s' % (data_host, fpath, qa_path)
                    _sshagent_run(cmd)

