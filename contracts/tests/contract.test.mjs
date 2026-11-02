import {test} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import ganache from 'ganache';
import {BrowserProvider,ContractFactory,Wallet,AbiCoder,keccak256,getBytes,randomBytes} from 'ethers';

test('NFT: unidad única, firma del propietario, límite, entrada única y cancelación',async()=>{
 const raw=ganache.provider({logging:{quiet:true},chain:{hardfork:'shanghai'},wallet:{totalAccounts:3}});
 try {
 const provider=new BrowserProvider(raw); const operator=await provider.getSigner(0);const other=await provider.getSigner(1);
 const artifact=JSON.parse(fs.readFileSync(new URL('../artifacts/NexoPass.json',import.meta.url)));
 const contract=await new ContractFactory(artifact.abi,artifact.bytecode,operator).deploy(await operator.getAddress());await contract.waitForDeployment();
 const owner=Wallet.createRandom(),recipient=Wallet.createRandom();
 const block=await provider.getBlock('latest');const starts=block.timestamp+172800,ends=starts+14400,doors=starts-3600,deadline=starts-86400;
 const event=keccak256(getBytes(randomBytes(32))),unit=keccak256(getBytes(randomBytes(32))),unit2=keccak256(randomBytes(32));
 await (await contract.configureEvent(event,starts,ends,doors,deadline)).wait();await(await contract.allowUnits(event,[unit,unit2])).wait();
 await(await contract.mintTicket(1,event,unit,owner.address)).wait();assert.equal(await contract.ownerOf(1),owner.address);
 await assert.rejects(contract.mintTicket(2,event,unit,recipient.address));
 await assert.rejects(contract.connect(other).mintTicket(3,event,unit,recipient.address));
 await assert.rejects(provider.call({to:await contract.getAddress(),from:owner.address,data:contract.interface.encodeFunctionData('transferFrom',[owner.address,recipient.address,1])}));
 await(await contract.mintTicket(2,event,unit2,owner.address)).wait();
 const expires=block.timestamp+3600,op=keccak256(randomBytes(32)),chain=await provider.getNetwork();
 const message=keccak256(AbiCoder.defaultAbiCoder().encode(['uint256','address','uint256','address','address','uint32','uint64','bytes32'],[chain.chainId,await contract.getAddress(),1,owner.address,recipient.address,1,expires,op]));
 await assert.rejects(contract.transferAuthorized(1,recipient.address,1,expires,op,await recipient.signMessage(getBytes(message))));
 await(await contract.transferAuthorized(1,recipient.address,1,expires,op,await owner.signMessage(getBytes(message)))).wait();
 assert.equal(await contract.ownerOf(1),recipient.address);assert.equal((await contract.tickets(1)).transfers,1n);
 await assert.rejects(contract.transferAuthorized(1,owner.address,2,expires,keccak256(randomBytes(32)),await recipient.signMessage(getBytes(message))));
 await assert.rejects(contract.consume(1,recipient.address,2,keccak256(randomBytes(32))));
 await raw.request({method:'evm_increaseTime',params:[172800]});await raw.request({method:'evm_mine',params:[]});
 await(await contract.consume(1,recipient.address,2,keccak256(randomBytes(32)))).wait();
 assert.equal((await contract.tickets(1)).used,true);
 await assert.rejects(contract.consume(1,recipient.address,2,keccak256(randomBytes(32))));
 await(await contract.cancelEvent(event)).wait();assert.equal((await contract.events(event)).cancelled,true);
 await assert.rejects(contract.consume(2,owner.address,1,keccak256(randomBytes(32))));
 }finally{await raw.disconnect()}
});
