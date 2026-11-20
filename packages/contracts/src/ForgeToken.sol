// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {ERC20} from "./ERC20.sol";

/// @title ForgeToken ($FORGE)
/// @notice Protocol token: governance weight, staking, fee-share, and AI-model
///         marketplace incentives. Minting is capped and controlled by the
///         emissions minter (a timelock-owned EmissionsController in production).
contract ForgeToken is ERC20 {
    uint256 public constant MAX_SUPPLY = 100_000_000e18;

    address public minter;

    event MinterUpdated(address indexed minter);

    modifier onlyMinter() {
        require(msg.sender == minter, "FORGE: not minter");
        _;
    }

    constructor(address _minter, address treasury, uint256 genesisToTreasury)
        ERC20("OracleForge", "FORGE", 18)
    {
        minter = _minter;
        if (genesisToTreasury > 0) {
            require(genesisToTreasury <= MAX_SUPPLY, "FORGE: cap");
            _mint(treasury, genesisToTreasury);
        }
        emit MinterUpdated(_minter);
    }

    function setMinter(address _minter) external onlyMinter {
        minter = _minter;
        emit MinterUpdated(_minter);
    }

    function mint(address to, uint256 amount) external onlyMinter {
        require(totalSupply + amount <= MAX_SUPPLY, "FORGE: cap");
        _mint(to, amount);
    }
}
