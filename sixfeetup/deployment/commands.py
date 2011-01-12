import os
import pickle
import re
import distutils.version
from fabric.api import env
from fabric.api import local
from fabric.api import prompt
from fabric.api import settings
from fabric.api import abort
from fabric.api import cd
from fabric.contrib.console import confirm
from fabric import colors
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

# URL to the trac instance base
env.trac_url_base = 'https://trac.sixfeetup.com'
# This is the trac/svn/dist name
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
env.qa_host = "sfupqaapp01"
# Base path to instances
env.base_qa_path = "/var/db/zope/dev"
#env.base_staging_path = "/var/db/zope/maint"


def deploy(show_diffs='on'):
    """Start the deployment process for this project
    """
    _release_manager_warning()
    choose_packages(show_diffs, save_choices='yes')
    release_packages(save_choices='yes')
    bump_package_versions()
    update_versions_cfg()
    tag_buildout()
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
            abort("Something went wrong, probably a version mismatch")
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


def tag_buildout():
    if not env.to_release:
        return
    print colors.blue("Tagging buildout")
    wc = py.path.svnwc('.')
    trunk_url = wc.url
    base_dir = wc.svnurl().dirpath().url
    with open('version.txt') as f:
        version = f.read().strip()
    local("svn cp -m 'tagging for release' %s %s/tags/%s" % (
        trunk_url, base_dir, version))
    # now bump the version and commit
    with open('version.txt', 'w') as f:
        new_version = _next_minor_version(version)
        f.write(new_version)
    local("svn ci -m 'bumping version for next release' version.txt")
