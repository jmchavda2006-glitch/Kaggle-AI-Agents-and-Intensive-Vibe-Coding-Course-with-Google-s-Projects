FROM python:3.11-slim
WORKDIR /app

# Create a secure non-root user and group
RUN groupadd -g 1000 myuser && \
    useradd -u 1000 -g myuser -m -s /bin/bash myuser

# Set up runtime directory ownership
RUN chown -R myuser:myuser /app

# Switch to the secure non-root user
USER myuser
ENV PATH="/home/myuser/.local/bin:$PATH"

# Copy and install python dependencies
COPY --chown=myuser:myuser requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# Copy the ambient expense agent codebase
COPY --chown=myuser:myuser ambient_expense_agent/ /app/ambient_expense_agent/

# Expose the API server port
EXPOSE 8000

# Set production environment defaults (can be overridden in K8s)
ENV POLICY_SERVER_URL="http://127.0.0.1:8181/v1/data/expense/allow"
ENV POLICY_SERVER_MOCK="false"

# Start the ADK API server and register the ZeroTrustPolicyPlugin dynamically
CMD ["adk", "api_server", "--host=0.0.0.0", "--port=8000", "--extra_plugins=ambient_expense_agent.policy_plugin.ZeroTrustPolicyPlugin", "/app/ambient_expense_agent"]
