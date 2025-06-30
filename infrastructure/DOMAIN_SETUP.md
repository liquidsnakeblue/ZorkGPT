# Hosting ZorkGPT at zorkgpt.schuyler.ai

This guide explains how to deploy the ZorkGPT frontend to your custom domain `zorkgpt.schuyler.ai`.

## Prerequisites

Before deploying, you need to ensure you have a hosted zone for `schuyler.ai` in AWS Route53. This is required for the SSL certificate validation and DNS record creation.

### Option 1: If you already have schuyler.ai hosted zone in Route53
✅ You're ready to deploy! The infrastructure will automatically find your existing hosted zone.

### Option 2: If you DON'T have schuyler.ai in Route53 yet
You need to create a hosted zone first. You can either:

1. **Transfer your entire domain to Route53** (recommended):
   ```bash
   # This will be done through the AWS Console
   # Go to Route53 > Hosted Zones > Create Hosted Zone
   # Domain name: schuyler.ai
   # Then update your domain registrar's nameservers to use Route53's nameservers
   ```

2. **Create a delegated subdomain** (if you want to keep your main domain elsewhere):
   ```bash
   # Create a hosted zone for just the subdomain
   # This requires adding NS records at your current DNS provider
   ```

## Deployment Steps

1. **Navigate to the infrastructure directory**:
   ```bash
   cd infrastructure
   ```

2. **Deploy the infrastructure**:
   ```bash
   python deploy.py
   ```

3. **Wait for certificate validation** (5-10 minutes):
   - The SSL certificate needs to be validated via DNS
   - AWS will automatically create the required DNS records in your hosted zone
   - You can monitor progress in the AWS Certificate Manager console

4. **Verify deployment**:
   - Check that the CloudFront distribution is deployed
   - Verify the Route53 A record for `zorkgpt.schuyler.ai` points to CloudFront
   - Test the URL: `https://zorkgpt.schuyler.ai`

## What Gets Created

The deployment creates:

- **S3 Bucket**: Stores the HTML files and game state
- **CloudFront Distribution**: CDN for fast global access
- **SSL Certificate**: Enables HTTPS for your domain
- **Route53 A Record**: Points `zorkgpt.schuyler.ai` to CloudFront
- **EC2 Instance**: Runs the ZorkGPT game and uploads state to S3

## Important Notes

- **HTTPS Only**: The site will redirect HTTP to HTTPS automatically
- **Certificate Region**: SSL certificates for CloudFront must be in `us-east-1`
- **DNS Propagation**: It may take up to 48 hours for DNS changes to propagate globally
- **CloudFront Deployment**: Initial CloudFront deployment takes 15-20 minutes

## Troubleshooting

### Certificate Validation Fails
- Ensure you have a hosted zone for `schuyler.ai` in Route53
- Check that the DNS validation records were created automatically
- Wait up to 30 minutes for validation to complete

### Domain Not Resolving
- Verify the Route53 A record exists for `zorkgpt.schuyler.ai`
- Check your domain registrar's nameservers point to Route53 (if using Route53 for the entire domain)
- Wait for DNS propagation (up to 48 hours)

### CloudFront Returns 403 Error
- The S3 bucket may be empty initially
- Wait for the EC2 instance to start and upload the HTML files
- Check EC2 instance logs: `sudo journalctl -u zorkgpt -f`

## Manual DNS Setup (Alternative)

If you prefer to manage DNS outside of Route53, you can:

1. Deploy the stack without the Route53 record
2. Get the CloudFront distribution domain name from the stack outputs
3. Create a CNAME record at your DNS provider:
   ```
   zorkgpt.schuyler.ai CNAME d123456789.cloudfront.net
   ```

Note: You'll still need Route53 for SSL certificate validation, or you can use manual certificate validation.

## Monitoring

After deployment, you can monitor the system:

- **CloudFront Metrics**: AWS CloudFront console
- **EC2 Instance**: SSH using the provided command in deployment outputs
- **Application Logs**: `sudo journalctl -u zorkgpt -f`
- **Game State**: Check S3 bucket for `current_state.json` updates

## Cost Estimation

Monthly costs (approximate):
- **S3**: $1-5 (depending on usage)
- **CloudFront**: $1-10 (depending on traffic)
- **Route53**: $0.50 per hosted zone
- **EC2**: $10-20 (t3.micro instance)
- **Certificate**: Free

Total: ~$12-35/month depending on usage