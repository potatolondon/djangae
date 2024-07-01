import os
from setuptools import setup, find_packages


NAME = "djangae"
PACKAGES = find_packages()
DESCRIPTION = "Django integration with Google App Engine"
URL = "https://gitlab.com/potato-oss/djangae/djangae"
LONG_DESCRIPTION = open(os.path.join(os.path.dirname(__file__), "README.md")).read()
AUTHOR = "Potato London Ltd."

EXTRAS = {
    "test": ["beautifulsoup4"],
}

if os.environ.get("CI_COMMIT_TAG"):
    VERSION = os.environ["CI_COMMIT_TAG"]
else:
    VERSION = "2.0.0rc5"

setup(
    name=NAME,
    version=VERSION,
    packages=PACKAGES,
    # metadata for upload to PyPI
    author=AUTHOR,
    author_email="mail@p.ota.to",
    description=DESCRIPTION,
    long_description=LONG_DESCRIPTION,
    long_description_content_type="text/markdown",
    keywords=["django", "Google App Engine", "GAE"],
    url=URL,
    classifiers=[
        "Development Status :: 4 - Beta",
        "Framework :: Django",
        "Framework :: Django :: 2.2",
        "Framework :: Django :: 3.2",
        "Framework :: Django :: 4.1",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: BSD License",
        "Operating System :: OS Independent",
        "Programming Language :: Python",
    ],
    include_package_data=True,
    # dependencies
    install_requires=[
        "django>=2.2,<5.0",
        "django-gcloud-connectors>=0.3.5,<1.3.0",
        "google-api-python-client>=2.27.0",
        "google-cloud-tasks>=2.0.0",
        "google-cloud-logging>=3.0.0,<4.0.0",
        "psutil>=5.7.3",
        # requests required by cloud storage file backend
        "requests>=2.22.0",
        "python-jose[cryptography]==3.2.0",
        "google-cloud-storage==1.43.0",
        # required minimum version for oauth backend
        "google-auth>=2.3.2,<3.0dev",
    ],
    extras_require=EXTRAS,
    tests_require=EXTRAS["test"],
)
