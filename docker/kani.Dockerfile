FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl git build-essential pkg-config \
    clang llvm \
 && rm -rf /var/lib/apt/lists/*

# Install rustup
RUN curl https://sh.rustup.rs -sSf | sh -s -- -y
ENV PATH="/root/.cargo/bin:${PATH}"

# Install Kani + download its bundle
RUN cargo install --locked kani-verifier
RUN cargo kani setup

RUN chmod 755 /root \
 && chmod -R a+rX /root/.cargo /root/.rustup /root/.kani

WORKDIR /work
