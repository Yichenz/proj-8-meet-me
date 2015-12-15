#
#  Build the application
#

# Configuration options
#
# On most platforms: 
#PYVENV = pyvenv-3.4
# On ix (with bug in ubuntu)
PYVENV = pyvenv-3.4 --without-pip


##
## Install in a new environment:
##     We need to rebuild the Python environment to match
##     Everything is straightforward EXCEPT that we need 
##     to work around an ubuntu bug in pyvenv on ix
##     
install:
	# pyvenv-3.4 env ### BUGGY on ix
	$(PYVENV)  env
	make env/bin/pip
	(.  env/bin/activate; pip install -r requirements.txt)

env/bin/pip: env/bin/activate
	echo ""
	(.  env/bin/activate; curl https://bootstrap.pypa.io/get-pip.py | python)


dist:
	pip freeze >requirements.txt
