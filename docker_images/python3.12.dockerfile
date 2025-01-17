FROM python:3.12
SHELL ["/bin/bash", "-c"]
RUN apt-get update
RUN apt-get install -y default-jre
RUN pip install tox
RUN gcloud version || true
RUN if [ ! -d "$HOME/google-cloud-sdk/bin" ]; then rm -rf $HOME/google-cloud-sdk; export CLOUDSDK_CORE_DISABLE_PROMPTS=1; curl https://sdk.cloud.google.com | bash; fi
RUN source /root/google-cloud-sdk/path.bash.inc && gcloud version
RUN CLOUDSDK_CORE_DISABLE_PROMPTS=1 source /root/google-cloud-sdk/path.bash.inc && gcloud components install cloud-datastore-emulator beta
