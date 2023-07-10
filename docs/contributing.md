# Contributing to Djangae

Djangae is actively developed and maintained, so if you're thinking of contributing to the codebase, here is how to get started.

## Get started with development

1. First off, head to [our GitLab page](https://gitlab.com/potato-oss/djangae/djangae) and fork the repository to have your own copy of it.
2. Clone it locally to start setting up your development environment
3. Run all tests to make sure your local version is working (see instructions in README.md).

## Pick an issue & send a merge request

If you spotted a bug in Djangae that you want to fix, it's a good idea to start
off by [adding an issue](https://gitlab.com/potato-oss/djangae/djangae/-/issues/new).
This will allow us to verify that your issue is valid, and suggest ideas for fixing it, so
no time is wasted for you.

For help with creating the merge request, check out [GitLab documentation](https://docs.gitlab.com/ee/user/project/merge_requests/creating_merge_requests.html).


## Djangae RFCs
The "RFC" (request for comments) process is intended to provide a consistent and controlled path for changes to Djangae (such as new substancial features).

Many changes, including bug fixes and documentation improvements should be implemented and reviewed via the normal workflow.

Some changes though are "substantial", and we may ask that these be put through a bit of a design process and produce a consensus among the team and community.

### When you need to follow this process
You need to follow this process if you intend to make "substantial" changes to Djangae, or the RFC process itself.
What constitutes a "substantial" change is easily definable and evolves, but it may include the following:

Breaking changes to the library.
Deprecations of features.
Substancial new features.

Some changes do not require an RFC:

Rephrasing, reorganizing, refactoring, or otherwise "changing shape does not change meaning".
Additions that strictly improve objective, numerical quality criteria (warning removal, speedup, better platform coverage, more parallelism, trap more errors, etc.)
Additions only likely to be noticed by other developers-of-djangae, invisible to users-of-djangae.

If you're unsure if an RFC is required or not, you can assume it is not, and submit an issue first.
If the team realises an RFC is indeed require, we will polititly request to submit an RFC first.

### What the process is

- Duplicate rfcs/0000-template.md to rfcs/0000-my-feature.md (where "my-feature" is descriptive). Don't assign an RFC number yet; This is going to be the PR number and we'll rename the file accordingly if the RFC is accepted.
- Fill in the RFC. Put care into the details: RFCs that do not present convincing motivation, demonstrate lack of understanding of the design's impact, or are disingenuous about the drawbacks or alternatives tend to be poorly-received.
- Submit a merge request. As a merge request the RFC will receive design feedback from the team, and the author should be prepared to revise it in response.
- Now that your RFC has an open pull request, use the issue number of the MR to update your 0000- prefix to that number.

## Code style

Code style should follow PEP-8 with a loose line length of 100 characters.

## Need help?

Reach out to us on [djangae-users](https://groups.google.com/forum/#!forum/djangae-users) mailing list.

## Merge request requirements

For pull request to be merged, following requirements should be met:

- Tests covering new or changed code are added or updated
- Relevant documentation should be updated or added
- Line item should be added to CHANGELOG.md, unless change is really irrelevant


## Running tests

On setting up the first time, create a Python 3 virtualenv and install the prerequisites with

```
# install tox
pip install tox

# install the datastore emulator
gcloud components install cloud-datastore-emulator
```

If you don't have `gcloud` (the Google Cloud SDK) installed, installation instructions can be found [here](https://cloud.google.com/sdk/install)

For running the tests, you just need to run:

    $ tox -e py310


You can run specific tests in the usual way by doing:

    tox -e py310 -- some_app.SomeTestCase.some_test_method
