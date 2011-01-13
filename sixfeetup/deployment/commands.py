from fabric import api
from sixfeetup.deployment.release import SETUPPY_VERSION
from sixfeetup.deployment.release import *
from sixfeetup.deployment.data import *

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
