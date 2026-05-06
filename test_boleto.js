const axios = require('axios');
const https = require('https');
const fs = require('fs');

const agent = new https.Agent({
    cert: fs.readFileSync('Sandbox_InterAPI_Certificado.crt'),
    key: fs.readFileSync('Sandbox_InterAPI_Chave.key'),
    rejectUnauthorized: false
});

async function test() {
    try {
        const tokenRes = await axios.post('https://cdpj-sandbox.partners.uatinter.co/oauth/v2/token', 'client_id=33d4df34-4160-4dc4-a586-c3785bc121bf&client_secret=e1c14579-2a77-436d-ad64-62e0333c955b&scope=boleto-cobranca.read boleto-cobranca.write&grant_type=client_credentials', {
            headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
            httpsAgent: agent
        });
        const token = tokenRes.data.access_token;
        console.log('Token:', token);

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
                "cep": "01001000"
            }
        };

        const urls = [
            'https://cdpj-sandbox.partners.uatinter.co/cobranca/v3/cobrancas'
        ];

        for (const u of urls) {
            try {
                console.log('Testing', u);
                const r = await axios.post(u, payload, {
                    headers: { 
                        'Authorization': `Bearer ${token}`,
                        'x-conta-corrente': '1234567890'
                    },
                    httpsAgent: agent
                });
                console.log('Success!', u, r.data);
                return;
            } catch (e) {
                console.log('Error', u, e.response?.status, e.response?.data);
            }
        }
    } catch (e) {
        console.error(e.message);
    }
}
test();
