import subprocess
import re
import os
from fabric import local
from py.path import svnwc, svnurl
from fabric import ENV as config
TRUISMS = [
    "true",
    "1",
    "yes",
    "y",
    "sure"
]
YES_OR_NO = ['yes', 'y', 'no', 'n']
PASS_ME = ['none', 'skip', 's']

#SETUPPY_VERSION = r"version.*['"](.*)(?:dev)['"]"
#METADATA_VERSION = r"<version>(.*)</version>"

DIFF_HELP_TEXT = """
Current tags: %(current_tags)s
Select a tag to compare with the current version, you can (s)kip
%(package)s"""

TAG_HELP_TEXT = """
Current tags: %(current_tags)s
Enter a tag name for %(package)s"""

def deploy(diffs=True):
    """This is the actual command we are going to run
    """
    showDiffs()
    tagPackages()
    releaseToSkillet()

def raw_default(prompt, default=None):
    if default is not None:
        prompt = "%s [default=%s]: " % (prompt, default)
    else:
        prompt = "%s:" % prompt
    res = raw_input(prompt)
    if not res and default is not None:
        return default
    return res

def getPackageList():
    """Compute the list of packages to diff, tag, etc.
    """
    ignore_dirs = config.package_ignores
    # XXX don't hardcode me
    ignore_dirs = ignore_dirs + ['.svn', 'CVS']
    packages = []
    package_dirs = config.package_dirs
    # find all the packages in the given package dirs
    for package_dir in package_dirs:
        items = os.listdir(package_dir)
        for item in items:
            if item not in ignore_dirs:
                package_path = '%s/%s' % (package_dir, item)
                if os.path.isdir(package_path):
                    packages.append(package_path)
    config.packages = packages

def findTagsURL(wc):
    """Find the wcpath/tags/ url so we can tag the package
    
    XXX this assumes that we have normal trunk/tags/branches in svn
    """
    url = wc.url.strip('/')
    url_parts = url.split('/')
    base_name = wc.svnurl().basename
    if base_name != 'trunk':
        # XXX this is a bit presumptious
        # remove the branches or tags
        del url_parts[-2]
    url_parts.remove(base_name)
    base_url = '/'.join(url_parts)
    return svnurl("%s/tags" % base_url)

def showDiffs():
    """
    """
    to_release = []
    getPackageList()
    for package in config.packages:
        wc = svnwc(package)
        wc_url = wc.url
        tags_url = findTagsURL(wc)
        current_tags = map(lambda x: x.basename, tags_url.listdir())
        cmp_tag = None
        while True:
            help_txt = DIFF_HELP_TEXT % locals()
            default_tag = 'None'
            if len(current_tags) > 0:
                default_tag = current_tags[-1]
            cmp_tag = raw_default(help_txt, default_tag)
            if cmp_tag.lower() in PASS_ME or cmp_tag in current_tags:
                break
        if cmp_tag.lower() not in PASS_ME:
            local('svn diff %(tags_url)s/%(cmp_tag)s %(wc_url)s' % locals())
        while True:
            release_package = raw_default("Does '%s' need a release?" % package, default="no").lower()
            if release_package in TRUISMS:
                to_release.append(package)
            # make sure the quesition was answered properly
            if release_package in YES_OR_NO:
                break
    config.to_release = to_release

def tagPackages():
    """
    """
    print config.to_release
    tagged = []
    for package in config.to_release:
        wc = svnwc(package)
        tags_url = findTagsURL(wc)
        help_txt = "Do you want to tag %s" % package
        do_tag = raw_default(help_txt, "yes")
        if do_tag.lower() in TRUISMS:
            current_tags = map(lambda x: x.basename, tags_url.listdir())
            tag_nums = '0.1'
            if current_tags:
                last_tag = current_tags[-1]
                # XXX we will assume X.X version numbers for now
                #     with no extra bells and whistles
                tag_nums = last_tag.split('.')
            try:
                next_num = int(tag_nums[1]) + 1
                if next_num == 10:
                    next_num = 0
                    tag_nums[0] = str(int(tag_nums[0]) + 1)
                tag_nums[1] = str(next_num)
                default_tag = '.'.join(tag_nums)
            except ValueError:
                default_tag = None
            help_txt = TAG_HELP_TEXT % locals()
            new_tag = raw_default(help_txt, default_tag)
            new_tag_url = svnurl("%s/%s" % (tags_url.url, new_tag))
            tag_msg = "Tagging %(package)s version %(new_tag)s for release" % locals()
            wc.svnurl().copy(new_tag_url, tag_msg)
            tagged.append(new_tag_url)
    # XXX remove this crap later...
    for i in tagged:
        print i
    config.tagged_packages = tagged

def releaseToSkillet():
    """
    This most certainly is not fail proof.  be warned!!!
    """
    # this could get ugly, quick
    urls = config.tagged_packages
    # make sure and set the environ so that bad things don't
    # happen with tar on os x
    os.environ['COPYFILE_DISABLE'] = 'True'
    co_cmd = "svn co %s %s"
    
    # XXX this is assuming that version is set in the setup.py
    #     and not read from another file
    version_re = re.compile(r"""(version.*=.*['"])(.*)(['"])""", re.M)
    
    # let's do it in tmp
    os.chdir('/tmp')
    for url in urls:
        help_txt = "Do you want to release '%s' to the skillet" % url
        do_skillet = raw_default(help_txt, "yes")
        if do_skillet.lower() in TRUISMS:
            # if the url is an svnurl we need to make it a string
            url = str(url)
            # remove a trailing slash
            if url[-1] == '/':
                url = url[:-1]
            parts = url.split('/')
            # this assumes a tag...
            version = parts[-1]
            name = parts[-3]
            co_name = "%s-%s" % (name, version)
            # check out the code
            runme = co_cmd % (url, co_name)
            subprocess.call(runme.split())
            os.chdir(co_name)
            if os.path.exists('setup.py'):
                sfname =  "setup.py"
                sf = open(sfname, 'r')
                sf_contents = sf.read()
                sf.close()
                sf = open(sfname, 'w')
                sf_new = version_re.sub('\g<1>' + version + '\g<3>', sf_contents)
                sf.write(sf_new)
                sf.close()
                print "committing updated version for %s" % co_name
                subprocess.call(['svn', 'ci', '-m', '"updating version for release"', '.'])
                # XXX make this configurable on a per item basis
                eggserver = config.get('eggserver', 'skillet')
                print "uploading new egg for %s to %s" % (co_name, eggserver)
                runme = "python setup.py mregister sdist mupload -r %s" % eggserver
                subprocess.call(runme.split())
            else:
                print "%s does not have a setup.py" % url
            os.chdir('..')
