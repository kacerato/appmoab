const https = require('https');
const fs = require('fs');
const axios = require('axios');
const crypto = require('crypto');

const certPath = 'Sandbox_InterAPI_Certificado.crt';
const keyPath = 'Sandbox_InterAPI_Chave.key';

try {
    const cert = fs.readFileSync(certPath);
    const key = fs.readFileSync(keyPath);

    // Verify if key and cert match
    const certObj = new crypto.X509Certificate(cert);
    console.log('Cert Subject:', certObj.subject);
    console.log('Cert Issuer:', certObj.issuer);
    
    // Apenas tenta conectar
    console.log('AIA:', certObj.infoAccess);
    
    const agent = new https.Agent({
        cert: cert,
        key: key,
        rejectUnauthorized: false,
        secureOptions: require('constants').SSL_OP_LEGACY_SERVER_CONNECT
    });

    console.log('Tentando conectar...');
    axios.post('https://cdpj-sandbox.partners.uatinter.co/oauth/v2/token', 'client_id=33d4df34-4160-4dc4-a586-c3785bc121bf&client_secret=e1c14579-2a77-436d-ad64-62e0333c955b&scope=boleto-cobranca.read boleto-cobranca.write&grant_type=client_credentials', {
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        httpsAgent: agent
    }).then(async res => {
        const token = res.data.access_token;
        console.log('Token obtido:', token);
        
        const payload = {
            "seuNumero": "TESTE-12345",
            "valorNominal": 10.50,
            "dataVencimento": "2026-12-31",
            "numDiasAgenda": 30,
            "pagador": {
                "cpfCnpj": "12345678909",
                "tipoPessoa": "FISICA",
                "nome": "João da Silva Teste",
                "endereco": "Rua Teste",
                "numero": "123",
                "bairro": "Centro",
                "cidade": "São Paulo",
                "uf": "SP",
                "cep": "01001000",
                "email": "teste@teste.com",
                "ddd": "11",
                "telefone": "999999999"
            }
        };

        try {
            console.log('Testando V3...');
            const r3 = await axios.post('https://cdpj-sandbox.partners.uatinter.co/cobranca/v3/boletos', payload, {
                headers: { 'Authorization': `Bearer ${token}` },
                httpsAgent: agent
            });
            console.log('V3 Sucesso:', r3.data);
        } catch(e) {
            console.log('Erro V3:', e.response ? e.response.status + ' ' + JSON.stringify(e.response.data) : e.message);
            try {
                console.log('Testando PIX...');
                const rPix = await axios.post('https://cdpj-sandbox.partners.uatinter.co/pix/v2/cob', {
                    calendario: { expiracao: 3600 },
                    devedor: { cpf: "12345678909", nome: "Teste" },
                    valor: { original: "10.00" },
                    chave: "f15e8b4e-28ce-41b9-8c0c-a98835848bb6" // random uuid
                }, {
                    headers: { 'Authorization': `Bearer ${token}` },
                    httpsAgent: agent
                });
                console.log('PIX Sucesso:', rPix.data);
            } catch(e2) {
                console.log('Erro PIX:', e2.response ? e2.response.status + ' ' + JSON.stringify(e2.response.data) : e2.message);
            }
        }

    }).catch(err => {
        console.log('Erro HTTPS:', err.message);
    });

} catch (e) {
    console.error('Script Error:', e);
}
