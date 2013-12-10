import os
import pickle
import re
import pkg_resources

from fabric import colors
from fabric import api
from fabric import contrib

from jarn.mkrelease.scm import SCMFactory
from jarn.mkrelease.setuptools import Setuptools

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
Enter a tag to release to %(target)s"""
DEFAULT_HOSTS = {
    'testing': ['sfupqaapp01'],
    'staging': ['sfupstaging01'],
}
DEFAULT_PATHS = {
    'testing': '/var/db/zope/dev',
    'staging': '/var/db/zope',
}


def deploy(env='testing', diffs='on'):
    """Start the deployment process for this project
    """
    _release_manager_warning()
    if env == 'testing':
        api.env.scm_factory = SCMFactory()
        api.env.setuptools = Setuptools()
        choose_packages(diffs, save_choices='yes')
        release_packages(save_choices='yes')
        bump_package_versions()
        update_versions_cfg()
        tag_buildout()
        #TODO: get automated release working
        #release_to(env)
    else:
        #TODO: get automated release working
        #eval("release_to(%s)" % env)
        pass
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
    get_info = api.env.setuptools.get_package_info
    # find all the packages in the given package dirs
    for package_dir in api.env.package_dirs:
        abs_package_dir = os.path.abspath(os.path.expanduser(package_dir))
        items = os.listdir(abs_package_dir)
        for item in items:
            if item in ignore_dirs:
                continue
            package_path = os.path.join(abs_package_dir, item)
            if not os.path.isdir(package_path):
                continue
            with api.lcd(package_path):
                # get the actual package name and version via mkrelease
                # TODO: handle dev release
                pkg_name, pkg_ver = get_info(package_path, develop=False)
            safe_pkg_name = pkg_resources.safe_name(pkg_name)
            if safe_pkg_name != pkg_name:
                msg = "\nSafe package name for %s used: %s"
                print colors.yellow(msg % (pkg_name, safe_pkg_name))
            api.env.package_info.setdefault(safe_pkg_name, {})
            api.env.package_info[safe_pkg_name]['path'] = package_path
            api.env.package_info[safe_pkg_name]['version'] = pkg_ver
            api.env.package_info[safe_pkg_name]['unsafe_name'] = pkg_name
            api.env.packages.append(safe_pkg_name)
    if verbose.lower() in TRUISMS:
        print """
Packages available:
%s
""" % "\n".join(api.env.packages)


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
        package_info = api.env.package_info[package]
        wc_path = package_info['path']
        wc = api.env.scm_factory.get_scm_from_sandbox(wc_path)

        if show_diff.lower() in TRUISMS:
            current_tags, current_tags_string = _get_tags(wc_path)
            cmp_tag = None
            while True:
                help_txt = DIFF_HELP_TEXT % locals()
                default_tag = 'None'
                if len(current_tags) > 0:
                    default_tag = current_tags[-1]
                cmp_tag = api.prompt(help_txt, default=default_tag)
                tagid = wc.make_tagid(wc_path, cmp_tag)
                if cmp_tag.lower() in PASS_ME or cmp_tag in current_tags:
                    break
            if cmp_tag.lower() not in PASS_ME:
                print wc.diff_tag(wc_path, tagid)
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
        current_version = package_info['version']
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
                cmd % ("-Cp", package_target, package_path),
                capture=True)
        if output.failed:
            print output
            api.abort(output.stderr)

        api.env.package_info[package]['version'] = current_version
        api.env.package_info[package]['next_version'] = _next_minor_version(
            current_version)
        api.env.package_info[package]['released_version'] = current_version
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
        wc = api.env.scm_factory.get_scm_from_sandbox(package_info['path'])
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
            wc.commit_sandbox(package_info['path'],
                              package,
                              next_version,
                              True)

def _get_buildout_version():
    with open('version.txt') as f:
        return f.read().strip()

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
    cwd = os.getcwd()
    wc = api.env.scm_factory.get_scm_from_sandbox(cwd)
    name = os.path.basename(cwd)
    buildout_ver = _get_buildout_version()
    wc.commit_sandbox(cwd, name, buildout_ver, True)



def _get_buildout_url():
    """Get the base buildout url
    """
    scm = SCMFactory()
    wc = scm.get_scm_from_sandbox(os.getcwd())
    sandbox_url = wc.get_url_from_sandbox(os.getcwd())
    base_dir = wc.get_base_url_from_sandbox(os.getcwd())
    return sandbox_url, base_dir


def tag_buildout():
    if not api.env.to_release:
        do_release = contrib.console.confirm(\
                        "No packages selected; release only buildout?",
                        default=False)
        if not do_release:
            api.abort("You didn't want to release")
    print colors.blue("Tagging buildout")
    cwd = os.getcwd()
    wc = api.env.scm_factory.get_scm_from_sandbox(cwd)
    version = _get_buildout_version()
    tagid = wc.make_tagid(cwd, version)
    name = os.path.basename(cwd)
    wc.create_tag(cwd, tagid, name, version, True)
    # now bump the version and commit
    with open('version.txt', 'w') as f:
        new_version = _next_minor_version(version)
        f.write(new_version)
    api.env.deploy_tag = version
    wc.commit_sandbox(cwd, name, new_version, True)


def release_to(target='testing'):
    """Release to a particular environment: testing, staging, prod
    """
    print colors.blue("Releasing to: %s" % target)
    if target == 'prod':
        do_release = contrib.console.confirm("Are you sure?", default=False)
        if not do_release:
            api.abort("You didn't want to release")
    api.env.deploy_env = target
    hosts = api.env.get('%s_hosts' % target,
                        DEFAULT_HOSTS.get(target, []))
    for host in hosts:
        with api.settings(host_string=host):
            _release_to_env()


def _get_tags(wc_path):
    wc = api.env.scm_factory.get_scm_from_sandbox(wc_path)
    with api.lcd(wc_path):
        current_tags = sorted(wc.list_tags(wc_path),
                              key=lambda x: pkg_resources.parse_version(x))
    return (current_tags,
            "\n    ".join(current_tags) or "No tags created yet")


def _release_to_env():
    base_env_path = "base_%s_path" % api.env.deploy_env
    base_path = api.env.get(base_env_path,
                            DEFAULT_PATHS.get(api.env.deploy_env))
    if not base_path:
        api.abort("Couldn't find %s" % base_env_path)
    buildout_name = api.env.get("%s_buildout_name" % api.env.deploy_env,
                                api.env.project_name)
    if not buildout_name:
        api.abort("Buildout name not defined for %s" % api.env.deploy_env)
    # check for the buildout
    buildout_dir = "%s/%s" % (base_path, buildout_name)
    trunk_url, base_url = _get_buildout_url()

    if not api.env.deploy_tag:
        current_tags, current_tags_string = _get_tags(os.getcwd())
        target = api.env.deploy_env
        help_txt = TAG_HELP_TEXT % locals()
        if len(current_tags) > 0:
            default_tag = current_tags[-1]
        api.env.deploy_tag = api.prompt(help_txt, default=default_tag)

    tag_url = "%s/tags/%s" % (base_url, api.env.deploy_tag)
    if not contrib.files.exists(buildout_dir):
        api.abort(
            "You need to create the initial api.env first: %s" % buildout_dir)
        # TODO: add to supervisor configs
        #with cd(base_path):
             # NOTE: can't use jarn.mkrelease to abstract scm actions here,
             #       unless it's installed on the remote machine
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
        # TODO: Check for changes in the buildout
        # switch to the new tag
        api.sudo("svn switch %s" % tag_url, user='zope')
        api.sudo("svn up", user='zope')
        # TODO: check for issues with switch
        # run buildout
        api.sudo("bin/buildout -v", user='zope')
    # start instance
    api.run("supervisorctl start %s" % supervisor_processes)
