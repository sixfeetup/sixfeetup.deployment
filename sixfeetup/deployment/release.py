import os
import pickle
import re
import distutils.version
from fabric import colors
from fabric import api
from fabric import contrib
import py.path
from sixfeetup.deployment.utils import GLOBAL_IGNORES
from sixfeetup.deployment.utils import TRUISMS
from sixfeetup.deployment.utils import YES_OR_NO

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
