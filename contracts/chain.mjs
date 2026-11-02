import ganache from 'ganache';
import path from 'node:path';
import os from 'node:os';
const server=ganache.server({chain:{chainId:31337,hardfork:'shanghai'},wallet:{totalAccounts:3},database:{dbPath:path.join(os.homedir(),'NexoPassData','chain')},logging:{quiet:true}});
await server.listen(8545,'127.0.0.1');
console.log('Blockchain local de pruebas: http://127.0.0.1:8545 (sin valor monetario real).');
for(const signal of ['SIGINT','SIGTERM']) process.on(signal,async()=>{await server.close();process.exit(0)});
