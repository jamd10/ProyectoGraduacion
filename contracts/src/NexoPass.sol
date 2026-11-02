// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "@openzeppelin/contracts/token/ERC721/ERC721.sol";
import "@openzeppelin/contracts/access/AccessControl.sol";
import "@openzeppelin/contracts/utils/cryptography/ECDSA.sol";
import "@openzeppelin/contracts/utils/cryptography/MessageHashUtils.sol";

/// @notice Prototipo nominativo: el operador verifica identidades fuera de cadena.
contract NexoPass is ERC721, AccessControl {
    bytes32 public constant OPERATOR_ROLE = keccak256("OPERATOR_ROLE");
    struct EventInfo { uint64 starts; uint64 ends; uint64 doors; uint64 deadline; bool cancelled; uint256 issued; }
    struct Ticket { bytes32 eventRef; bytes32 unitRef; uint32 version; uint8 transfers; bool used; bool cancelled; }
    mapping(bytes32 => EventInfo) public events;
    mapping(uint256 => Ticket) public tickets;
    mapping(bytes32 => bool) public allowedUnits;
    mapping(bytes32 => bool) public mintedUnits;
    mapping(bytes32 => bool) public executed;
    bool private controlled;
    event TicketIssued(uint256 indexed tokenId, bytes32 indexed eventRef, address indexed owner);
    event TicketReassigned(uint256 indexed tokenId, uint32 version);
    event TicketConsumed(uint256 indexed tokenId, bytes32 operation);
    event EventCancelled(bytes32 indexed eventRef);

    constructor(address operator) ERC721("NexoPass", "NEXO") {
        _grantRole(DEFAULT_ADMIN_ROLE, operator);
        _grantRole(OPERATOR_ROLE, operator);
    }
    function supportsInterface(bytes4 interfaceId) public view override(ERC721, AccessControl) returns (bool) {
        return super.supportsInterface(interfaceId);
    }
    function configureEvent(bytes32 ref, uint64 starts, uint64 ends, uint64 doors, uint64 deadline) external onlyRole(OPERATOR_ROLE) {
        require(ends > starts && doors <= starts && deadline + 1 days <= starts, "Invalid times");
        EventInfo storage e = events[ref];
        require(!e.cancelled, "Cancelled event");
        if(e.issued > 0) require(e.starts==starts && e.ends==ends && e.doors==doors && e.deadline==deadline, "Issued event immutable");
        e.starts=starts; e.ends=ends; e.doors=doors; e.deadline=deadline;
    }
    function allowUnits(bytes32 eventRef, bytes32[] calldata units) external onlyRole(OPERATOR_ROLE) {
        require(events[eventRef].starts != 0 && !events[eventRef].cancelled, "Invalid event");
        for(uint256 i; i<units.length; ++i) allowedUnits[keccak256(abi.encode(eventRef, units[i]))]=true;
    }
    function mintTicket(uint256 tokenId, bytes32 eventRef, bytes32 unitRef, address owner) external onlyRole(OPERATOR_ROLE) {
        bytes32 unitKey=keccak256(abi.encode(eventRef, unitRef));
        require(!events[eventRef].cancelled && events[eventRef].starts>block.timestamp, "Event unavailable");
        require(allowedUnits[unitKey] && !mintedUnits[unitKey], "Unit unavailable");
        mintedUnits[unitKey]=true;
        tickets[tokenId]=Ticket(eventRef, unitRef, 1, 0, false, false);
        events[eventRef].issued++;
        _mint(owner,tokenId);
        emit TicketIssued(tokenId,eventRef,owner);
    }
    function transferAuthorized(uint256 tokenId, address recipient, uint32 expectedVersion, uint64 expires, bytes32 operation, bytes calldata signature) external onlyRole(OPERATOR_ROLE) {
        Ticket storage t=tickets[tokenId];
        address owner=ownerOf(tokenId);
        require(!t.used && !t.cancelled && !events[t.eventRef].cancelled, "Inactive ticket");
        require(t.transfers==0 && t.version==expectedVersion && block.timestamp<events[t.eventRef].deadline, "Transfer unavailable");
        require(block.timestamp<=expires && !executed[operation], "Expired or replayed");
        bytes32 authorization=keccak256(abi.encode(block.chainid,address(this),tokenId,owner,recipient,expectedVersion,expires,operation));
        require(ECDSA.recover(MessageHashUtils.toEthSignedMessageHash(authorization),signature)==owner, "Owner signature required");
        executed[operation]=true;
        t.transfers=1; t.version++;
        controlled=true;
        _transfer(owner,recipient,tokenId);
        controlled=false;
        emit TicketReassigned(tokenId,t.version);
    }
    function consume(uint256 tokenId, address expectedOwner, uint32 expectedVersion, bytes32 operation) external onlyRole(OPERATOR_ROLE) {
        Ticket storage t=tickets[tokenId]; EventInfo storage e=events[t.eventRef];
        require(ownerOf(tokenId)==expectedOwner && t.version==expectedVersion, "Stale authorization");
        require(!t.used && !t.cancelled && !e.cancelled && !executed[operation], "Inactive ticket");
        require(block.timestamp>=e.doors && block.timestamp<=e.ends, "Outside admission window");
        executed[operation]=true; t.used=true;
        emit TicketConsumed(tokenId,operation);
    }
    function cancelEvent(bytes32 ref) external onlyRole(OPERATOR_ROLE) {
        events[ref].cancelled=true; emit EventCancelled(ref);
    }
    function _update(address to, uint256 tokenId, address auth) internal override returns(address) {
        if(_ownerOf(tokenId)!=address(0)) require(controlled, "Use authorized transfer");
        return super._update(to,tokenId,auth);
    }
    function approve(address, uint256) public pure override { revert("Approvals disabled"); }
    function setApprovalForAll(address, bool) public pure override { revert("Approvals disabled"); }
}
