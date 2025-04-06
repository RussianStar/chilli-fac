I want to couple the watering and the light to mqtt based sensors.

There should be a list of sensors which can be added by the users. This is done from the user side by entering a form which has the topic id and the stage it is associated to. For example '732492342' and stage 2. So the program knows where to get the information and the stage it is at, so where to act.

The sensors has two values for now, temperature and soil moisture.

For each stage a lower bound soil moisture can be set. When the level is under this for at least 4 data points in a row trigger watering for this stage. The duration should be 300s for now. 

The mqtt server connection should be taken from the config and I will add it later myself.the sub topic is <server_address>/bodenfeuchte/<id> with data :
{
    soil_moisture: 12.8, temperature: 25.2
}



