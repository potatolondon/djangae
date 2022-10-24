import os
from setuptools import setup, find_packages


NAME = 'djangae'
PACKAGES = find_packages(exclude=["testapp", "testprodapp"])
DESCRIPTION = 'Django integration with Google App Engine'
URL = "https://github.com/potatolondon/djangae"
LONG_DESCRIPTION = open(os.path.join(os.path.dirname(__file__), 'README.md')).read()
AUTHOR = 'Potato London Ltd.'

EXTRAS = {
    "test": ["webtest"],
}

setup(
    name=NAME,
    version='1.1.0',
    packages=PACKAGES,

    # metadata for upload to PyPI
    author=AUTHOR,
    author_email='mail@p.ota.to',
    description=DESCRIPTION,
    long_description=LONG_DESCRIPTION,
    long_description_content_type='text/markdown',
    keywords=["django", "Google App Engine", "GAE"],
    url=URL,
    classifiers=[
        'Development Status :: 4 - Beta',
        'Framework :: Django',
        'Framework :: Django :: 1.8',
        'Framework :: Django :: 1.9',
        'Framework :: Django :: 1.10',
        'Framework :: Django :: 1.11',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: BSD License',
        'Operating System :: OS Independent',
        'Programming Language :: Python',
    ],

    include_package_data=True,
    # dependencies
    extras_require=EXTRAS,
    tests_require=EXTRAS['test'],
)
