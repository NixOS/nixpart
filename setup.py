#!/usr/bin/env python
import sys

from distutils.core import setup, Command
from unittest import TextTestRunner, TestLoader

PYTHON_MODULES = [
    'nixpart',
    'nixpart.main',
    'nixpart.args',
    'nixpart.storage',
    'nixpart.tests.args',
]


class RunTests(Command):
    description = 'run test suite'
    user_options = []
    initialize_options = finalize_options = lambda self: None

    def run(self):
        tests = TestLoader().discover('nixpart.tests', pattern='*.py')
        result = TextTestRunner(verbosity=1).run(tests)
        sys.exit(not result.wasSuccessful())

setup(name='nixpart',
      version='1.0.0',
      description='NixOS storage manager/partitioner',
      url='https://github.com/aszlig/nixpart',
      author='aszlig',
      author_email='aszlig@redmoonstudios.org',
      scripts=['scripts/nixpart'],
      py_modules=PYTHON_MODULES,
      cmdclass={'test': RunTests},
      license='GPL')
