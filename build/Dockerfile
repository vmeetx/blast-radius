# Makes ../map. Not part of the submitted image. The base is the one the top Dockerfile uses.
FROM python:3.13-slim@sha256:e48f59cdba69a3cbd9ed2cf0f348d90d45a8d350d98134cf1070bc106ee9ed90
COPY requirements.lock /requirements.lock
RUN pip install --no-cache-dir -r /requirements.lock
ADD https://github.com/tobymao/sqlglot/archive/eb11aec4be8cb2122afe713a4816662c3f0fb2fa.tar.gz /sqlglot.tar.gz
RUN mkdir /src && tar -xzf /sqlglot.tar.gz -C /src --strip-components=1 && chmod -R a+rX /src
COPY build /build
