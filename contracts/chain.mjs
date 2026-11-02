import readline from 'node:readline';
import ganache from 'ganache';
import path from 'node:path';
import os from 'node:os';
const server=ganache.server({chain:{chainId:31337,hardfork:'shanghai'},wallet:{totalAccounts:3,deterministic:true},database:{dbPath:path.join(process.env.NEXOPASS_DATA_DIRECTORY || path.join(os.homedir(),'NexoPassData'),'chain')},logging:{quiet:true}});
await server.listen(8545,'127.0.0.1');
console.log('Blockchain local de pruebas: http://127.0.0.1:8545 (sin valor monetario real).');
for(const signal of ['SIGINT','SIGTERM']) process.on(signal,async()=>{await server.close();process.exit(0)});

readline.createInterface({input:process.stdin}).on('line',async line=>{if(line==='shutdown'){await server.close();process.exit(0)}});
