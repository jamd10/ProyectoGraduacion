import ganache from './node_modules/ganache/dist/node/core.js';
const server=ganache.server({chain:{chainId:31337,hardfork:'shanghai'},logging:{quiet:true},wallet:{totalAccounts:3}});
await server.listen(Number(process.env.NEXOPASS_TEST_CHAIN_PORT || 18545),'127.0.0.1');console.log('Cadena E2E lista');
