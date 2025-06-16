# Changelog
All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.3.0] - 2025-06-16
### Added
- New Feature: Introduced Agent Engine Test tab.

### Fixed
- Renamed the V2 Agentspace registration Tabs since legacy APIs have been removed from solution.

### Removed
- Legacy registration of Agents with Agentspace tabs have been removed from UI.

## [0.2.0] - 2025-05-30
### Added
- New Feature: Support for Agent Engine in a different GCP project than the Agentspace.
- New Feature: Introduced new Agentspace APIs for registering Agent Engine ADK Agents. (denoted with V2 tabs)
- New Feature: Introduced OAuth Agentspace Authorizations for Agents that require OAuth scopes.

### Fixed
- Support Agent specific .env file variables getting properly mapped to Agent Engine at deployment time. New attribute for

## [0.1.0] - 2025-05-15
### Added
- Initial release of Agent Quick Deploy.