# Changelog
All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.5.0] - 2025-07-22
### Added
- New Feature: Support for custom service accounts for Agent Engines during deployment to better adhere to the principle of least privilege.
- The configured service account for each Agent Engine is now displayed on the Destroy tab.

## [0.4.0] - 2025-07-08
### Added
- New Feature: Can now list all OAuth Authorizations within the project and can select to delete one

### Fixed
- Refactored main agent_manager.py file, broken down into supporting modules, now located in the `agent_manager` directory.

## [0.3.0] - 2025-06-16
### Added
- New Feature: Introduced Agent Engine Test tab.

### Fixed
- Renamed the V2 Agentspace registration tabs since legacy APIs have been removed from solution.

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