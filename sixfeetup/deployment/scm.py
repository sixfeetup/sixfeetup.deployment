from os import linesep
from os.path import isdir

from jarn.mkrelease.scm import Subversion, Mercurial, Git

def list_svn_tags(self, dir):
    base_url = self.get_base_url_from_sandbox(dir)
    layout = self.get_layout_from_sandbox(dir)
    url = '/'.join([base_url, layout[2]])
    rc, lines = self.process.popen(
        'svn list "%(url)s"' % locals(), echo=False)
    return [line[:-1] for line in lines if rc == 0]


def diff_svn_tag(self, dir, tagid, use_colordiff=True):
    url = self.get_url_from_sandbox(dir)
    cmd = 'svn diff "%(tagid)s" "%(url)s"' % locals()
    if use_colordiff:
        cmd += ' | colordiff'
    rc, lines = self.process.popen(cmd, echo=False)
    return linesep.join([line for line in lines if rc == 0])


def list_hg_tags(self, dir):
    if isdir(dir):
        self.dirstack.push(dir)
        try:
            rc, lines = self.process.popen(
                'hg tags', echo=False)
            return [line for line in lines if rc == 0]
        finally:
            self.dirstack.pop()
    else:
        return []


def diff_hg_tag(self, dir, tagid):
    if isdir(dir):
        self.dirstack.push(dir)
        try:
            url = self.get_url_from_sandbox(dir)
            rc, lines = self.process.popen(
                'hg diff -r "%(tagid)s"' % locals(), echo=False)
            return linesep.join([line for line in lines if rc == 0])
        finally:
            self.dirstack.pop()
    else:
        return ''


def list_git_tags(self, dir):
    if isdir(dir):
        self.dirstack.push(dir)
        try:
            rc, lines = self.process.popen(
                'git tag', echo=False)
            return [line for line in lines if rc == 0]
        finally:
            self.dirstack.pop()
    else:
        return []


def diff_git_tag(self, dir, tagid):
    if isdir(dir):
        self.dirstack.push(dir)
        try:
            rc, lines = self.process.popen(
                'git diff --color=always "%(tagid)s" HEAD' % locals(),
                echo=False)
            return linesep.join([line for line in lines if rc == 0])
        finally:
            self.dirstack.pop()
    else:
        return ''


Subversion.list_tags = list_svn_tags
Subversion.diff_tag = diff_svn_tag
Mercurial.list_tags = list_hg_tags
Mercurial.diff_tag = diff_hg_tag
Git.list_tags = list_git_tags
Git.diff_tag = diff_git_tag
