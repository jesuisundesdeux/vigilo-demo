# Controller of the demo farm: docker CLI + compose, git, Python. The script itself is read
# from the checkout of the repository (DEMO_DIR), so it follows the repository.
FROM docker:29-cli
RUN apk add --no-cache python3 py3-yaml git \
    && git config --system --add safe.directory '*'
CMD ["sh", "-c", "exec python3 \"$DEMO_DIR/controller/vigilo-demo.py\" loop"]
