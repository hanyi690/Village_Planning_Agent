# Contract ports

Small dependency-inversion interfaces shared across modules and infrastructure.
Concrete providers implement these ports; business modules depend on the port,
not on provider SDKs or storage details.
