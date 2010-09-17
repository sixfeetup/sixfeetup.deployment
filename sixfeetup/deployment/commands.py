import os
from fabric.api import env
from fabric.api import local
from fabric.api import prompt
from fabric.contrib.console import confirm
from fabric import colors
from py.path import svnwc, svnurl

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
#SETUPPY_VERSION = r"version.*['"](.*)(?:dev)['"]"
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
# List of packages to release
env.to_release = []
# This is a directory that contains the eggs we want to release
env.package_dirs = ['src']
# List of package path names to ignore (e.g. 'my.package')
env.ignore_dirs = []


def deploy(show_diffs='on'):
    """Start the deployment process for this project
    """
    _release_manager_warning()
    choose_packages(show_diffs, save_choices='on')
    release_packages()
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
                    env.packages.append(package_path)
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
    return svnurl("%s/tags" % base_url)


def choose_packages(show_diff='yes', save_choices='no'):
    """Choose the packages that need to be released"""
    save_choices = save_choices.lower() in TRUISMS
    if (save_choices and
      os.path.exists('.saved_choices') and
      confirm("Do you want to use the previously saved choices?")):
        with open('.saved_choices') as f:
            env.to_release = f.read().split('\n')
        return
    elif os.path.exists('.saved_choices'):
        os.unlink('.saved_choices')
    list_package_candidates()
    for package in env.packages:
        wc = svnwc(package)
        wc_url = wc.url
        if show_diff.lower() in TRUISMS:
            tags_url = _find_tags_url(wc)
            current_tags = map(lambda x: x.basename, tags_url.listdir())
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
                local(
                    'svn diff %(tags_url)s/%(cmp_tag)s %(wc_url)s' % locals())
        while True:
            release_package = prompt(
                "Does '%s' need a release?" % package, default="no").lower()
            if release_package in TRUISMS:
                env.to_release.append(package)
            # make sure the question was answered properly
            if release_package in YES_OR_NO:
                break
    if save_choices:
        with open('.saved_choices', 'w') as f:
            f.write("\n".join(env.to_release))


def release_packages(dev="no"):
    if not env.to_release:
        print colors.blue("\nNo packages to release.")
    else:
        print colors.blue("\nReleasing packages")
        print "\n".join(env.to_release)
        print
    for package_path in env.to_release:
        cmd = "mkrelease %s -d %s %s"
        # TODO: handle dev release
        local(
            cmd % ("-C", env.default_release_target, package_path),
            capture=False)
